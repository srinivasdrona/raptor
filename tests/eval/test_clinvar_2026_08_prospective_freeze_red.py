from __future__ import annotations

import errno
import json
import os
import socket
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

import tests.eval._clinvar_2026_08_prospective_red_helpers as prospective_red_helpers
from tests.eval._clinvar_2026_08_prospective_red_helpers import (
    HISTORICAL_BLOCKED_PATH,
    REPO_ROOT,
    InjectedLookup,
    InjectedTransport,
    assert_record_content_hash,
    assert_stop_state,
    build_approval_record,
    build_scoring_stage_approval_record,
    canonical_json_content_hash,
    canonical_lf_sha256_path,
    execute_transport_and_raw_freeze,
    make_head_payload,
    md5_hex,
    merge_overlay,
    prospective_sandbox,
    projection_sha256_excluding_labels_snapshot,
    require_api,
    require_exception,
    require_module,
    runtime_identity_ok,
    validate_pre_data_approval,
    validate_scoring_stage_approval,
)


def _published_date_lookup_ok(url: str) -> InjectedLookup:
    return InjectedLookup(
        {
            url: {
                "published_archive_date": "2026-08-06",
                "source_identity": "ncbi-published-archive-index-2026-08",
            }
        }
    )


def _official_md5_lookup_ok(url: str, _archive_bytes: bytes) -> InjectedLookup:
    return InjectedLookup(
        {
            url: {
                "official_md5": None,
                "upstream_checksum_available": False,
                "source_identity": "ncbi-clinvar-monthly-archive-index",
                "unavailable_reason": "NCBI does not publish checksums for monthly archive copies",
                "verification_mode": "EXACT_URL_HEAD_CONTINUITY_PLUS_LOCAL_SHA256_MD5",
            }
        }
    )


def _assert_no_records_created(*paths: Path) -> None:
    for path in paths:
        assert not path.exists()


def _require_freeze_contract_symbols() -> None:
    require_api("execute_transport_and_raw_freeze")
    require_api("validate_pre_data_approval")
    require_api("merge_prospective_overlay")
    require_api("assert_runtime_boundary")
    require_api("MAX_DOWNLOAD_CHUNK_BYTES")
    require_api("PRE_DATA_STOP_STATES")
    require_api("HEAD_REASON_CODES")
    require_exception("ProspectiveContractError")
    require_exception("ProspectiveStopStateError")
    require_exception("ProspectiveInvalidStateError")
    stop_states = require_api("PRE_DATA_STOP_STATES")
    assert set(stop_states) == {
        "PRE_DATA_REVIEW_REQUIRED",
        "PRE_DATA_REJECTED",
        "PRE_DATA_IMPLEMENTATION_NOT_READY",
        "PRE_DATA_DRIFT",
        "PRE_DATA_ATTESTATION_BREACH",
    }
    head_reason_codes = require_api("HEAD_REASON_CODES")
    assert set(head_reason_codes) == {
        "HEAD_STATUS_MISMATCH",
        "HEAD_FINAL_URL_MISMATCH",
        "HEAD_LAST_MODIFIED_MISSING",
        "HEAD_LAST_MODIFIED_DUPLICATE",
        "HEAD_LAST_MODIFIED_MALFORMED",
        "HEAD_LAST_MODIFIED_MISMATCH",
        "HEAD_CONTENT_LENGTH_MISSING",
        "HEAD_CONTENT_LENGTH_DUPLICATE",
        "HEAD_CONTENT_LENGTH_MALFORMED",
        "HEAD_CONTENT_LENGTH_MISMATCH",
    }


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _can_create_symlink(parent: Path) -> bool:
    if not hasattr(os, "symlink"):
        return False
    probe_target = parent / "symlink-probe-target.txt"
    probe_link = parent / "symlink-probe-link.txt"
    probe_target.write_text("x", encoding="utf-8")
    try:
        os.symlink(probe_target, probe_link)
        return probe_link.is_symlink()
    except OSError:
        return False
    finally:
        try:
            probe_link.unlink(missing_ok=True)
        except OSError:
            pass
        probe_target.unlink(missing_ok=True)


_FIFO_UNSUPPORTED_ERRNOS = {
    code
    for code in (
        getattr(errno, "ENOTSUP", None),
        getattr(errno, "EOPNOTSUPP", None),
        getattr(errno, "ENOSYS", None),
    )
    if code is not None
}

_UNIX_UNSUPPORTED_ERRNOS = {
    code
    for code in (
        getattr(errno, "EAFNOSUPPORT", None),
        getattr(errno, "EPROTONOSUPPORT", None),
        getattr(errno, "ENOTSUP", None),
        getattr(errno, "EOPNOTSUPP", None),
        getattr(errno, "ENOSYS", None),
    )
    if code is not None
}

_UNIX_PATH_LIMIT_ERRNOS = {
    code
    for code in (
        getattr(errno, "ENAMETOOLONG", None),
        getattr(errno, "EINVAL", None),
    )
    if code is not None
}


def _is_unix_path_length_error(exc: OSError) -> bool:
    if exc.errno in _UNIX_PATH_LIMIT_ERRNOS:
        return True
    message = str(exc).lower()
    return "path too long" in message or "name too long" in message


def _probe_fifo_capability(parent: Path) -> tuple[bool, str]:
    if not hasattr(os, "mkfifo"):
        return False, "fifo creation unsupported: os.mkfifo unavailable"
    probe = parent / "fifo-capability-probe"
    probe.unlink(missing_ok=True)
    try:
        os.mkfifo(probe)
    except OSError as exc:
        if exc.errno in _FIFO_UNSUPPORTED_ERRNOS:
            return False, f"fifo creation unsupported on this filesystem/runtime (errno={exc.errno})"
        raise
    finally:
        probe.unlink(missing_ok=True)
    return True, ""


def _probe_unix_socket_capability_for_path(path: Path) -> tuple[bool, str]:
    if not hasattr(socket, "AF_UNIX"):
        return False, "unix sockets unsupported: socket.AF_UNIX unavailable"
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)

    short_probe = parent / "unix-socket-capability-probe.sock"
    short_probe.unlink(missing_ok=True)
    short_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        short_socket.bind(str(short_probe))
    except OSError as exc:
        if _is_unix_path_length_error(exc):
            return False, "unix socket path length unsupported for this sandbox path"
        if exc.errno in _UNIX_UNSUPPORTED_ERRNOS:
            return False, f"unix sockets unsupported on this filesystem/runtime (errno={exc.errno})"
        raise
    finally:
        short_socket.close()
        short_probe.unlink(missing_ok=True)

    required_total = len(os.fsencode(str(path)))
    parent_total = len(os.fsencode(str(parent)))
    probe_name_len = required_total - parent_total - 1
    if probe_name_len <= 0:
        return False, "unix socket path-length probe could not derive a valid filename"
    if probe_name_len > 255:
        return False, f"unix socket filename length unsupported for probe (bytes={probe_name_len})"
    length_probe = parent / ("u" * probe_name_len)
    length_probe.unlink(missing_ok=True)
    length_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        length_socket.bind(str(length_probe))
    except OSError as exc:
        if _is_unix_path_length_error(exc):
            return False, f"unix socket path length unsupported for this sandbox path (errno={exc.errno})"
        if exc.errno in _UNIX_UNSUPPORTED_ERRNOS:
            return False, f"unix sockets unsupported on this filesystem/runtime (errno={exc.errno})"
        raise
    finally:
        length_socket.close()
        length_probe.unlink(missing_ok=True)

    return True, ""


def _mutate_approval(
    approval: dict[str, Any],
    *,
    decision: str | None = None,
    approver: str | None = None,
    approved_at: str | None = None,
    protected_tests_verified: bool | None = None,
    add_field: tuple[str, Any] | None = None,
    scope_updates: dict[str, bool] | None = None,
    attestation_updates: dict[str, bool] | None = None,
    overlay_hash: str | None = None,
) -> dict[str, Any]:
    mutated = json.loads(json.dumps(approval))
    if decision is not None:
        mutated["decision"] = decision
    if approver is not None:
        mutated["approver"] = approver
    if approved_at is not None:
        mutated["approved_at"] = approved_at
    if protected_tests_verified is not None:
        mutated["protected_tests_verified"] = protected_tests_verified
    if add_field is not None:
        mutated[add_field[0]] = add_field[1]
    if scope_updates is not None:
        mutated["scope"].update(scope_updates)
    if attestation_updates is not None:
        mutated["pre_data_access_attestation"].update(attestation_updates)
    if overlay_hash is not None:
        mutated["overlay"]["canonical_lf_sha256"] = overlay_hash
    return mutated


def _replace_once_in_file(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    assert count == 1
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _files_under(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [entry for entry in root.rglob("*") if entry.is_file()]


def test_freeze_api_contract_and_typed_stop_state_codes_exist() -> None:
    _require_freeze_contract_symbols()


def test_stage12_success_returns_stage_scoped_status_and_never_terminal_pass() -> None:
    _require_freeze_contract_symbols()
    max_chunk = int(require_api("MAX_DOWNLOAD_CHUNK_BYTES"))
    assert max_chunk <= 8 * 1024 * 1024
    with prospective_sandbox("stage12-success") as sandbox:
        approval = build_approval_record(sandbox)
        probes: list[str] = []

        def _forbidden(name: str) -> Callable[..., None]:
            def _inner(*_args: Any, **_kwargs: Any) -> None:
                probes.append(name)
                raise AssertionError(f"{name} must be unreachable in freeze stages 1-2")

            return _inner

        transport = InjectedTransport(
            head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )
        published_lookup = _published_date_lookup_ok(sandbox.exact_url)
        md5_lookup = _official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes)
        result = execute_transport_and_raw_freeze(
            sandbox,
            approval_record=approval,
            transport=transport,
            published_archive_date_lookup=published_lookup,
            official_md5_lookup=md5_lookup,
            label_reader=_forbidden("label_reader"),
            benchmark_builder=_forbidden("benchmark_builder"),
            scoring_runner=_forbidden("scoring_runner"),
        )

        assert result["stage_status"] == "TRANSPORT_AND_RAW_FROZEN"
        assert result.get("terminal_outcome") is None
        assert result["transport_metadata_not_content_identity"] is True
        assert "runtime_identity" not in result
        assert "x64_freeze" not in approval
        assert result["download_chunk_bytes"] > 0
        assert result["download_chunk_bytes"] <= max_chunk
        assert published_lookup.calls == [sandbox.exact_url]
        assert md5_lookup.calls == [sandbox.exact_url]
        assert transport.head_calls == [sandbox.exact_url]
        assert transport.get_calls == [(sandbox.exact_url, result["download_chunk_bytes"])]
        assert probes == []

        archive_path = Path(result["raw_archive_path"]).resolve()
        assert _is_under(archive_path, sandbox.external_root)
        assert not _is_under(archive_path, sandbox.repo_root)
        assert archive_path.parent != sandbox.external_root.resolve()
        assert result["run_scope_id"] in archive_path.as_posix()

        transport_record = assert_record_content_hash(sandbox.transport_record_path)
        raw_record = assert_record_content_hash(sandbox.raw_record_path)
        assert transport_record["status"] == "TRANSPORT_FROZEN"
        assert raw_record["status"] == "RAW_ARCHIVE_FROZEN"
        assert raw_record["computed_md5"] == md5_hex(sandbox.archive_bytes)
        assert raw_record["raw_sha256"] == sha256_hex(sandbox.archive_bytes)
        assert raw_record["upstream_checksum_available"] is False
        assert raw_record["upstream_checksum_verified"] is False
        assert raw_record["content_verification_mode"] == "EXACT_URL_HEAD_CONTINUITY_PLUS_LOCAL_SHA256_MD5"
        assert result["computed_md5"] == raw_record["computed_md5"]
        assert result["raw_sha256"] == raw_record["raw_sha256"]


@pytest.mark.parametrize(
    ("case_id", "mutator", "first_get_at", "expected_stop"),
    (
        ("missing-approval", lambda _approval: None, None, "PRE_DATA_REVIEW_REQUIRED"),
        ("wrong-approver", lambda approval: _mutate_approval(approval, approver="@wrong"), None, "PRE_DATA_REVIEW_REQUIRED"),
        ("rejected", lambda approval: _mutate_approval(approval, decision="REJECTED_PRE_DATA"), None, "PRE_DATA_REJECTED"),
        ("stale-after-first-get", lambda approval: _mutate_approval(approval, approved_at="2026-08-29T11:00:00Z"), "2026-08-29T10:00:00Z", "PRE_DATA_DRIFT"),
        ("extra-top-level-field", lambda approval: _mutate_approval(approval, add_field=("unexpected_field", True)), None, "PRE_DATA_REVIEW_REQUIRED"),
        (
            "scope-allows-substitute",
            lambda approval: _mutate_approval(approval, scope_updates={"allow_substitute_archive": True}),
            None,
            "PRE_DATA_REVIEW_REQUIRED",
        ),
        (
            "reintroduced-immutable-inputs-verified-field",
            lambda approval: _mutate_approval(approval, add_field=("immutable_inputs_verified", False)),
            None,
            "PRE_DATA_REVIEW_REQUIRED",
        ),
        ("protected-tests-false", lambda approval: _mutate_approval(approval, protected_tests_verified=False), None, "PRE_DATA_IMPLEMENTATION_NOT_READY"),
        (
            "attestation-true",
            lambda approval: _mutate_approval(approval, attestation_updates={"archive_bytes_hashed": True}),
            None,
            "PRE_DATA_ATTESTATION_BREACH",
        ),
        ("approval-contract-drift", lambda approval: _mutate_approval(approval, overlay_hash="f" * 64), None, "PRE_DATA_DRIFT"),
    ),
)
def test_executor_pre_data_stop_states_are_typed_and_zero_network(
    case_id: str,
    mutator: Any,
    first_get_at: str | None,
    expected_stop: str,
) -> None:
    _require_freeze_contract_symbols()
    stop_error = require_exception("ProspectiveStopStateError")
    with prospective_sandbox(f"stop-state-{case_id}") as sandbox:
        base = build_approval_record(sandbox)
        approval = mutator(base)
        transport = InjectedTransport(
            head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )
        with pytest.raises(stop_error) as exc:
            execute_transport_and_raw_freeze(
                sandbox,
                approval_record=approval,
                transport=transport,
                published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
                official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
                first_archive_get_at=first_get_at,
            )
        assert_stop_state(exc.value, expected_stop)
        assert transport.head_calls == []
        assert transport.get_calls == []
        _assert_no_records_created(sandbox.transport_record_path, sandbox.raw_record_path)


@pytest.mark.parametrize(
    ("field_name", "drifted_value"),
    (
        ("bias_commit", "0" * 40),
        ("nirvana_banner", "3.18.1"),
        ("resource_manifest_sha256", "deadbeef"),
        ("worker_designation", "other-worker"),
        ("worker_arch", "arm64"),
    ),
)
def test_scoring_stage_approval_runtime_identity_drift_is_invalid_with_zero_network(
    field_name: str, drifted_value: str
) -> None:
    """`validate_scoring_stage_approval` -- the SEPARATE, LATER ADR-0022
    stage 4 gate -- rejects x64_freeze identity drift as INVALID (A0
    run-integrity), never a PRE_DATA_* stop state. This gate is never
    consulted by `execute_transport_and_raw_freeze` (stages 1-2), which is
    why this test never constructs a transport at all."""
    _require_freeze_contract_symbols()
    invalid_error = require_exception("ProspectiveInvalidStateError")
    with prospective_sandbox(f"scoring-stage-runtime-drift-{field_name}") as sandbox:
        approval = build_scoring_stage_approval_record(sandbox, x64_freeze_overrides={field_name: drifted_value})
        with pytest.raises(invalid_error) as exc:
            validate_scoring_stage_approval(sandbox, approval_record=approval)
        assert exc.value.code == "INVALID"


def test_scoring_config_drift_never_blocks_acquisition() -> None:
    """Finding #5 (independent review, boundary correction): acquisition
    (`build_approval_record`/`validate_pre_data_approval`/
    `execute_transport_and_raw_freeze`) never requires or verifies the
    registration spec's `immutable_inputs` (tsc2.yaml, ACMG/BIAS strength
    ladder/lineage, masking/predictor-aggregation policy, ...) at all --
    those are exclusively SCORING-stage inputs. Corrupting one of those
    real files on disk (drift that WOULD fail `validate_scoring_stage_
    approval`'s independent `immutable_inputs_verified` recomputation) must
    have zero effect on stage 1/2 ClinVar archive acquisition."""
    _require_freeze_contract_symbols()
    with prospective_sandbox("scoring-config-drift-does-not-block-acquisition") as sandbox:
        approval = build_approval_record(sandbox)
        assert "immutable_inputs_verified" not in approval

        # Corrupt one of the real scoring-stage immutable_inputs files that
        # `_copy_immutable_inputs` placed into the sandbox's own repo_root.
        drifted_config = sandbox.repo_root / "configs" / "eval" / "tsc2.yaml"
        drifted_config.write_bytes(drifted_config.read_bytes() + b"\n# scoring-config drift injected by test\n")

        transport = InjectedTransport(
            head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )
        result = execute_transport_and_raw_freeze(
            sandbox,
            approval_record=approval,
            transport=transport,
            published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
            official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
        )
        assert result["stage_status"] == "TRANSPORT_AND_RAW_FROZEN"

        # The SAME drift, however, must be caught by the separate,
        # scoring-stage gate's independent immutable_inputs recomputation.
        invalid_error = require_exception("ProspectiveInvalidStateError")
        scoring_approval = build_scoring_stage_approval_record(sandbox)
        with pytest.raises(invalid_error) as exc:
            validate_scoring_stage_approval(sandbox, approval_record=scoring_approval)
        assert exc.value.code == "INVALID"


def test_scoring_stage_approval_never_consulted_by_stage12_acquisition() -> None:
    """Acquisition (stages 1-2) never requires, reads, or checks x64/BIAS/
    Nirvana identity -- `execute_transport_and_raw_freeze` accepts no
    `runtime_identity` parameter and a `pre_data_approval` record has no
    `x64_freeze` key at all."""
    _require_freeze_contract_symbols()
    with prospective_sandbox("scoring-stage-not-consulted") as sandbox:
        approval = build_approval_record(sandbox)
        assert "x64_freeze" not in approval
        transport = InjectedTransport(
            head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )
        result = execute_transport_and_raw_freeze(
            sandbox,
            approval_record=approval,
            transport=transport,
            published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
            official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
        )
        assert result["stage_status"] == "TRANSPORT_AND_RAW_FROZEN"
        assert "runtime_identity" not in result


@pytest.mark.parametrize(
    ("case_id", "raw_headers", "expected_reason"),
    (
        (
            "last-modified-mismatch",
            lambda expected_len: [("Last-Modified", "Fri, 07 Aug 2026 04:05:02 GMT"), ("Content-Length", str(expected_len))],
            "HEAD_LAST_MODIFIED_MISMATCH",
        ),
        (
            "last-modified-missing",
            lambda expected_len: [("Content-Length", str(expected_len))],
            "HEAD_LAST_MODIFIED_MISSING",
        ),
        (
            "last-modified-malformed",
            lambda expected_len: [("Last-Modified", "not-a-date"), ("Content-Length", str(expected_len))],
            "HEAD_LAST_MODIFIED_MALFORMED",
        ),
    ),
)
def test_last_modified_cases_use_correct_content_length_and_reason_code(
    case_id: str,
    raw_headers: Callable[[int], list[tuple[str, str]]],
    expected_reason: str,
) -> None:
    _require_freeze_contract_symbols()
    with prospective_sandbox(f"last-modified-{case_id}") as sandbox:
        approval = build_approval_record(sandbox)
        expected_len = int(sandbox.spec["dataset_registration"]["stage_1_head_comparison"]["content_length_bytes_must_equal"])
        head_payload = make_head_payload(sandbox, raw_headers=raw_headers(expected_len))
        transport = InjectedTransport(
            head_by_url={sandbox.exact_url: head_payload},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )
        result = execute_transport_and_raw_freeze(
            sandbox,
            approval_record=approval,
            transport=transport,
            published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
            official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
        )
        assert result["terminal_outcome"] == "BLOCKED_DATA"
        assert result["reason_code"] == expected_reason
        assert transport.get_calls == []


@pytest.mark.parametrize(
    ("case_id", "raw_headers", "expected_outcome", "expected_reason"),
    (
        (
            "last-modified-duplicate",
            lambda expected_len: [("Last-Modified", "Thu, 06 Aug 2026 04:05:02 GMT"), ("Last-Modified", "Thu, 06 Aug 2026 04:05:02 GMT"), ("Content-Length", str(expected_len))],
            "INVALID",
            "HEAD_LAST_MODIFIED_DUPLICATE",
        ),
        (
            "content-length-missing",
            lambda _expected_len: [("Last-Modified", "Thu, 06 Aug 2026 04:05:02 GMT")],
            "BLOCKED_DATA",
            "HEAD_CONTENT_LENGTH_MISSING",
        ),
        (
            "content-length-duplicate",
            lambda expected_len: [("Last-Modified", "Thu, 06 Aug 2026 04:05:02 GMT"), ("Content-Length", str(expected_len)), ("Content-Length", str(expected_len))],
            "INVALID",
            "HEAD_CONTENT_LENGTH_DUPLICATE",
        ),
        (
            "content-length-malformed",
            lambda _expected_len: [("Last-Modified", "Thu, 06 Aug 2026 04:05:02 GMT"), ("Content-Length", "not-an-int")],
            "BLOCKED_DATA",
            "HEAD_CONTENT_LENGTH_MALFORMED",
        ),
        (
            "content-length-mismatch",
            lambda expected_len: [("Last-Modified", "Thu, 06 Aug 2026 04:05:02 GMT"), ("Content-Length", str(expected_len + 1))],
            "BLOCKED_DATA",
            "HEAD_CONTENT_LENGTH_MISMATCH",
        ),
    ),
)
def test_head_header_missing_duplicate_malformed_and_mismatch_cases(
    case_id: str,
    raw_headers: Callable[[int], list[tuple[str, str]]],
    expected_outcome: str,
    expected_reason: str,
) -> None:
    _require_freeze_contract_symbols()
    with prospective_sandbox(f"head-header-{case_id}") as sandbox:
        approval = build_approval_record(sandbox)
        expected_len = int(sandbox.spec["dataset_registration"]["stage_1_head_comparison"]["content_length_bytes_must_equal"])
        head_payload = make_head_payload(sandbox, raw_headers=raw_headers(expected_len))
        transport = InjectedTransport(
            head_by_url={sandbox.exact_url: head_payload},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )
        result = execute_transport_and_raw_freeze(
            sandbox,
            approval_record=approval,
            transport=transport,
            published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
            official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
        )
        assert result["terminal_outcome"] == expected_outcome
        assert result["reason_code"] == expected_reason


@pytest.mark.parametrize(
    ("case_id", "head_status", "head_final_url", "published_payload", "md5_payload", "expected_reason", "expected_gets"),
    (
        ("head-status", 404, None, "ok", "ok", "HEAD_STATUS_MISMATCH", 0),
        ("head-final-url", 200, "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/archive/variant_summary/variant_summary_2026-08.txt.gz", "ok", "ok", "HEAD_FINAL_URL_MISMATCH", 0),
        ("published-date-missing", 200, None, "missing", "ok", "PUBLISHED_ARCHIVE_DATE_MISSING", 0),
        ("published-date-malformed", 200, None, "malformed", "ok", "PUBLISHED_ARCHIVE_DATE_MALFORMED", 0),
        ("upstream-checksum-source-missing", 200, None, "ok", "source-missing", "UPSTREAM_CHECKSUM_SOURCE_MISSING", 0),
        ("upstream-checksum-policy-malformed", 200, None, "ok", "malformed", "UPSTREAM_CHECKSUM_POLICY_MALFORMED", 0),
    ),
)
def test_url_head_date_or_checksum_source_mismatch_cases_are_blocked_data(
    case_id: str,
    head_status: int,
    head_final_url: str | None,
    published_payload: str,
    md5_payload: str,
    expected_reason: str,
    expected_gets: int,
) -> None:
    _require_freeze_contract_symbols()
    with prospective_sandbox(f"blocked-data-{case_id}") as sandbox:
        approval = build_approval_record(sandbox)
        head_payload = make_head_payload(sandbox, status_code=head_status, final_url=head_final_url)
        transport = InjectedTransport(
            head_by_url={sandbox.exact_url: head_payload},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )

        published_lookup = _published_date_lookup_ok(sandbox.exact_url)
        if published_payload == "missing":
            published_lookup = InjectedLookup({sandbox.exact_url: None})
        elif published_payload == "malformed":
            published_lookup = InjectedLookup(
                {
                    sandbox.exact_url: {
                        "published_archive_date": "not-a-date",
                        "source_identity": "ncbi-published-archive-index-2026-08",
                    }
                }
            )

        md5_lookup = _official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes)
        if md5_payload == "source-missing":
            md5_lookup = InjectedLookup(
                {
                    sandbox.exact_url: {
                        "official_md5": None,
                        "upstream_checksum_available": False,
                        "source_identity": "",
                        "unavailable_reason": "not published",
                        "verification_mode": "EXACT_URL_HEAD_CONTINUITY_PLUS_LOCAL_SHA256_MD5",
                    }
                }
            )
        elif md5_payload == "malformed":
            md5_lookup = InjectedLookup(
                {
                    sandbox.exact_url: {
                        "official_md5": "0" * 32,
                        "upstream_checksum_available": True,
                        "source_identity": "ncbi-clinvar-monthly-archive-index",
                        "unavailable_reason": "not published",
                        "verification_mode": "EXACT_URL_HEAD_CONTINUITY_PLUS_LOCAL_SHA256_MD5",
                    }
                }
            )

        result = execute_transport_and_raw_freeze(
            sandbox,
            approval_record=approval,
            transport=transport,
            published_archive_date_lookup=published_lookup,
            official_md5_lookup=md5_lookup,
        )
        assert result["terminal_outcome"] == "BLOCKED_DATA"
        assert result["reason_code"] == expected_reason
        assert len(transport.get_calls) == expected_gets


def test_merge_overlay_changes_only_labels_snapshot_and_preserves_projection_hash() -> None:
    _require_freeze_contract_symbols()
    with prospective_sandbox("overlay-merge") as sandbox:
        base_eval_config = yaml.safe_load(sandbox.base_eval_config_path.read_text(encoding="utf-8"))
        if not isinstance(base_eval_config, dict):
            pytest.fail("base eval config must parse to mapping")

        pinned_projection = "a19f0b1825a3b5b9c5886cc783750cd907045601447cfd132329d3ab9b9e10b5"
        assert projection_sha256_excluding_labels_snapshot(base_eval_config) == pinned_projection

        merged_payload = merge_overlay(sandbox)
        assert set(merged_payload).issuperset(
            {
                "effective_eval_config",
                "overlay_path",
                "overlay_canonical_lf_sha256",
                "base_projection_sha256",
            }
        )
        assert merged_payload["overlay_path"] == str(sandbox.overlay_path)
        assert merged_payload["overlay_canonical_lf_sha256"] == canonical_lf_sha256_path(sandbox.overlay_path)
        assert merged_payload["base_projection_sha256"] == pinned_projection

        merged_eval = merged_payload["effective_eval_config"]
        assert isinstance(merged_eval, dict)
        assert merged_eval["labels_snapshot"] == sandbox.overlay["effective_labels_snapshot"]
        for key, value in base_eval_config.items():
            if key == "labels_snapshot":
                continue
            assert merged_eval[key] == value
        assert projection_sha256_excluding_labels_snapshot(merged_eval) == pinned_projection


def test_overlay_and_spec_lf_drift_are_typed_pre_data_drift_before_network() -> None:
    _require_freeze_contract_symbols()
    stop_error = require_exception("ProspectiveStopStateError")

    with prospective_sandbox("overlay-drift") as sandbox:
        approval = build_approval_record(sandbox)
        sandbox.overlay_path.write_text(
            sandbox.overlay_path.read_text(encoding="utf-8") + "\n# drift\n",
            encoding="utf-8",
        )
        transport = InjectedTransport(
            head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )
        with pytest.raises(stop_error) as exc:
            execute_transport_and_raw_freeze(
                sandbox,
                approval_record=approval,
                transport=transport,
                published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
                official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
            )
        assert_stop_state(exc.value, "PRE_DATA_DRIFT")
        assert transport.head_calls == []
        assert transport.get_calls == []

    with prospective_sandbox("spec-drift") as sandbox:
        approval = build_approval_record(sandbox)
        sandbox.spec_path.write_text(
            sandbox.spec_path.read_text(encoding="utf-8") + "\n# drift\n",
            encoding="utf-8",
        )
        transport = InjectedTransport(
            head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )
        with pytest.raises(stop_error) as exc:
            execute_transport_and_raw_freeze(
                sandbox,
                approval_record=approval,
                transport=transport,
                published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
                official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
            )
        assert_stop_state(exc.value, "PRE_DATA_DRIFT")
        assert transport.head_calls == []
        assert transport.get_calls == []


def test_overlay_cli_env_override_and_default_live_socket_paths_are_blocked() -> None:
    _require_freeze_contract_symbols()
    invalid_error = require_exception("ProspectiveInvalidStateError")
    with prospective_sandbox("override-socket-guard") as sandbox:
        approval = build_approval_record(sandbox)
        with pytest.raises(invalid_error) as exc_override:
            execute_transport_and_raw_freeze(
                sandbox,
                approval_record=approval,
                transport=InjectedTransport(
                    head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
                    body_by_url={sandbox.exact_url: sandbox.archive_bytes},
                ),
                published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
                official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
                cli_overrides={"labels_snapshot": "forbidden"},
                env_overrides={"RAPTOR_LABELS_SNAPSHOT_OVERRIDE": "forbidden"},
            )
        assert getattr(exc_override.value, "code", None) == "INVALID"

        socket_calls: list[Any] = []
        original_socket = socket.socket

        def _deny_socket(*args: Any, **kwargs: Any) -> Any:
            socket_calls.append((args, kwargs))
            raise AssertionError("default live transport socket path must be unreachable in tests")

        socket.socket = _deny_socket
        try:
            with pytest.raises(invalid_error) as exc_default_transport:
                execute_transport_and_raw_freeze(
                    sandbox,
                    approval_record=approval,
                    transport=None,
                    published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
                    official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
                )
            assert getattr(exc_default_transport.value, "code", None) == "INVALID"
            assert socket_calls == []
        finally:
            socket.socket = original_socket


@pytest.mark.parametrize(
    "destination_case",
    ("path-traversal", "symlink-inside", "symlink-outside", "dangling-symlink", "fifo", "special-socket-file"),
)
def test_destination_boundary_probes_cover_traversal_symlink_fifo_specialfile(destination_case: str) -> None:
    _require_freeze_contract_symbols()
    with prospective_sandbox(f"destination-{destination_case}") as sandbox:
        approval = build_approval_record(sandbox)
        transport = InjectedTransport(
            head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )
        destination = sandbox.transport_record_path
        destination.parent.mkdir(parents=True, exist_ok=True)

        if destination_case in {"symlink-inside", "symlink-outside", "dangling-symlink"} and not _can_create_symlink(sandbox.root):
            pytest.skip("symlink creation unsupported in this environment")

        if destination_case == "path-traversal":
            destination = sandbox.root / "outside" / "transport.json"
            destination.parent.mkdir(parents=True, exist_ok=True)
        elif destination_case == "symlink-inside":
            inside_target = sandbox.repo_root / "inside-target.json"
            inside_target.parent.mkdir(parents=True, exist_ok=True)
            inside_target.write_text("{}", encoding="utf-8")
            os.symlink(inside_target, destination)
        elif destination_case == "symlink-outside":
            outside_target = sandbox.root / "outside-target.json"
            outside_target.write_text("{}", encoding="utf-8")
            os.symlink(outside_target, destination)
        elif destination_case == "dangling-symlink":
            os.symlink(sandbox.root / "missing-target.json", destination)
        elif destination_case == "fifo":
            fifo_supported, fifo_reason = _probe_fifo_capability(destination.parent)
            if not fifo_supported:
                pytest.skip(fifo_reason)
            try:
                os.mkfifo(destination)
            except OSError as exc:
                if exc.errno in _FIFO_UNSUPPORTED_ERRNOS:
                    pytest.skip(f"fifo creation unsupported for destination path (errno={exc.errno})")
                raise
        elif destination_case == "special-socket-file":
            unix_supported, unix_reason = _probe_unix_socket_capability_for_path(destination)
            if not unix_supported:
                pytest.skip(unix_reason)
            unix_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                unix_socket.bind(str(destination))
            except OSError as exc:
                if exc.errno in _UNIX_UNSUPPORTED_ERRNOS or _is_unix_path_length_error(exc):
                    pytest.skip(f"unix socket destination unsupported in this environment (errno={exc.errno})")
                raise
            finally:
                unix_socket.close()
        else:  # pragma: no cover
            pytest.fail(f"unknown destination case: {destination_case}")

        result = execute_transport_and_raw_freeze(
            sandbox,
            approval_record=approval,
            transport=transport,
            published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
            official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
            transport_record_path=destination,
        )
        assert result["terminal_outcome"] == "INVALID"
        assert result["reason_code"]


def test_partial_write_crash_cleanup_via_monkeypatched_atomic_writer() -> None:
    _require_freeze_contract_symbols()
    module = require_module()
    invalid_error = require_exception("ProspectiveInvalidStateError")
    writer_name = None
    for candidate in ("_atomic_write_json", "atomic_write_json", "_atomic_replace_json", "_atomic_replace"):
        if hasattr(module, candidate):
            writer_name = candidate
            break
    if writer_name is None:
        pytest.fail("RED: missing planned atomic write primitive for crash simulation")

    with prospective_sandbox("atomic-crash") as sandbox:
        approval = build_approval_record(sandbox)
        original = getattr(module, writer_name)
        state = {"calls": 0}

        def _crash_after_first(*args: Any, **kwargs: Any) -> Any:
            state["calls"] += 1
            if state["calls"] == 1:
                return original(*args, **kwargs)
            raise RuntimeError("simulated crash")

        setattr(module, writer_name, _crash_after_first)
        try:
            with pytest.raises(invalid_error) as exc:
                execute_transport_and_raw_freeze(
                    sandbox,
                    approval_record=approval,
                    transport=InjectedTransport(
                        head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
                        body_by_url={sandbox.exact_url: sandbox.archive_bytes},
                    ),
                    published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
                    official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
                )
            assert getattr(exc.value, "code", None) == "INVALID"
        finally:
            setattr(module, writer_name, original)

        assert sandbox.transport_record_path.exists()
        assert_record_content_hash(sandbox.transport_record_path)
        assert not sandbox.raw_record_path.exists()

        checked_dirs = {sandbox.transport_record_path.parent.resolve(), sandbox.raw_record_path.parent.resolve()}
        for directory in checked_dirs:
            entries = [item.name for item in directory.iterdir() if item.is_file()]
            allowed = {sandbox.transport_record_path.name}
            unexpected = [name for name in entries if name not in allowed]
            assert not unexpected


def test_restart_idempotence_and_hash_chain_distinguish_data_mismatch_vs_corruption() -> None:
    _require_freeze_contract_symbols()
    with prospective_sandbox("restart-idempotence") as sandbox:
        approval = build_approval_record(sandbox)
        first_transport = InjectedTransport(
            head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )
        first = execute_transport_and_raw_freeze(
            sandbox,
            approval_record=approval,
            transport=first_transport,
            published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
            official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
        )
        assert first["stage_status"] == "TRANSPORT_AND_RAW_FROZEN"
        assert len(first_transport.get_calls) == 1
        transport_bytes = sandbox.transport_record_path.read_bytes()
        raw_bytes = sandbox.raw_record_path.read_bytes()

        second_transport = InjectedTransport(
            head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )
        second = execute_transport_and_raw_freeze(
            sandbox,
            approval_record=approval,
            transport=second_transport,
            published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
            official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
        )
        assert second["stage_status"] == "TRANSPORT_AND_RAW_FROZEN"
        assert second.get("idempotent_reuse") is True
        assert sandbox.transport_record_path.read_bytes() == transport_bytes
        assert sandbox.raw_record_path.read_bytes() == raw_bytes

        raw_payload = json.loads(sandbox.raw_record_path.read_text(encoding="utf-8"))
        raw_payload["content_verification_mode"] = "UNSAFE"
        raw_payload["content_hash"] = canonical_json_content_hash(raw_payload)
        sandbox.raw_record_path.write_text(json.dumps(raw_payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        blocked = execute_transport_and_raw_freeze(
            sandbox,
            approval_record=approval,
            transport=InjectedTransport(
                head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
                body_by_url={sandbox.exact_url: sandbox.archive_bytes},
            ),
            published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
            official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
        )
        assert blocked["terminal_outcome"] == "INVALID"
        assert blocked["reason_code"] == "CONTENT_VERIFICATION_MODE_INVALID"

        corrupted_payload = json.loads(sandbox.raw_record_path.read_text(encoding="utf-8"))
        corrupted_payload["content_hash"] = "f" * 64
        sandbox.raw_record_path.write_text(json.dumps(corrupted_payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        invalid = execute_transport_and_raw_freeze(
            sandbox,
            approval_record=approval,
            transport=InjectedTransport(
                head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
                body_by_url={sandbox.exact_url: sandbox.archive_bytes},
            ),
            published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
            official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
        )
        assert invalid["terminal_outcome"] == "INVALID"


def test_concurrent_writer_allows_dual_idempotent_or_typed_single_stop() -> None:
    _require_freeze_contract_symbols()
    stop_error = require_exception("ProspectiveStopStateError")
    invalid_error = require_exception("ProspectiveInvalidStateError")
    with prospective_sandbox("concurrency") as sandbox:
        approval = build_approval_record(sandbox)
        start_barrier = threading.Barrier(2)
        worker_entered = [threading.Event(), threading.Event()]

        class _LatchedConcurrentTransport(InjectedTransport):
            def __init__(self) -> None:
                super().__init__(
                    head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
                    body_by_url={sandbox.exact_url: sandbox.archive_bytes},
                )
                self.first_get_entered = threading.Event()
                self.second_get_entered = threading.Event()
                self.release_get = threading.Event()

            def stream_get(self, url: str, chunk_bytes: int):  # type: ignore[override]
                with self._lock:
                    self.get_calls.append((url, chunk_bytes))
                    ordinal = len(self.get_calls)
                if url not in self._body_by_url:
                    raise AssertionError(f"unexpected GET URL: {url}")
                if ordinal == 1:
                    self.first_get_entered.set()
                elif ordinal == 2:
                    self.second_get_entered.set()
                self.release_get.wait(timeout=10)
                payload = self._body_by_url[url]
                step = max(1, min(chunk_bytes, 17))
                for idx in range(0, len(payload), step):
                    yield payload[idx : idx + step]

        shared_transport = _LatchedConcurrentTransport()
        shared_date_lookup = _published_date_lookup_ok(sandbox.exact_url)
        shared_md5_lookup = _official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes)
        results: list[dict[str, Any]] = []
        errors: list[BaseException] = []
        lock = threading.Lock()

        def _worker(index: int) -> None:
            try:
                worker_entered[index].set()
                start_barrier.wait(timeout=10)
                out = execute_transport_and_raw_freeze(
                    sandbox,
                    approval_record=approval,
                    transport=shared_transport,
                    published_archive_date_lookup=shared_date_lookup,
                    official_md5_lookup=shared_md5_lookup,
                )
                with lock:
                    results.append(out)
            except (stop_error, invalid_error) as exc:
                with lock:
                    errors.append(exc)

        t1 = threading.Thread(target=_worker, args=(0,), daemon=True)
        t2 = threading.Thread(target=_worker, args=(1,), daemon=True)
        t1.start()
        t2.start()

        assert worker_entered[0].wait(timeout=10)
        assert worker_entered[1].wait(timeout=10)
        assert shared_transport.first_get_entered.wait(timeout=10)
        shared_transport.second_get_entered.wait(timeout=2)
        shared_transport.release_get.set()

        t1.join(timeout=30)
        t2.join(timeout=30)

        assert len(results) + len(errors) == 2
        assert len(results) >= 1
        assert len(shared_transport.get_calls) == 1
        assert not shared_transport.second_get_entered.is_set()
        if len(results) == 2:
            for item in results:
                assert item["stage_status"] == "TRANSPORT_AND_RAW_FROZEN"
        else:
            assert len(results) == 1
            assert len(errors) == 1
            assert getattr(errors[0], "code", None) in {"PRE_DATA_DRIFT", "INVALID", "CONCURRENT_WRITE"}

        transport_record = assert_record_content_hash(sandbox.transport_record_path)
        raw_record = assert_record_content_hash(sandbox.raw_record_path)
        for item in results:
            if item.get("transport_record_content_hash") is not None:
                assert item["transport_record_content_hash"] == transport_record["content_hash"]
            if item.get("raw_record_content_hash") is not None:
                assert item["raw_record_content_hash"] == raw_record["content_hash"]


def test_transport_identity_pin_mismatch_on_entry_refuses_before_any_network_call() -> None:
    """Finding #1 (independent review): if `transport`'s class methods are
    already monkeypatched (simulating tampering that happened between pin
    capture and this call) by the time `execute_transport_and_raw_freeze`
    is entered, the supplied `transport_identity_pin` mismatch is detected
    immediately, and no `head`/`stream_get` call is ever made."""
    _require_freeze_contract_symbols()
    module = require_module()
    with prospective_sandbox("transport-pin-mismatch-on-entry") as sandbox:
        approval = build_approval_record(sandbox)
        transport = InjectedTransport(
            head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )
        pin = module.capture_transport_identity_pin(transport)

        # Simulate tampering that happened AFTER the pin was captured
        # (e.g. by a caller-selected lookup module) but BEFORE this call.
        original_stream_get = type(transport).stream_get
        type(transport).stream_get = lambda self, url, chunk_bytes: (_ for _ in ()).throw(
            AssertionError("tampered stream_get must never be reached")
        )
        try:
            result = execute_transport_and_raw_freeze(
                sandbox,
                approval_record=approval,
                transport=transport,
                published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
                official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
                transport_identity_pin=pin,
            )
        finally:
            type(transport).stream_get = original_stream_get
        assert result == {
            "stage_status": "BLOCKED",
            "terminal_outcome": "INVALID",
            "reason_code": "TRANSPORT_IDENTITY_TAMPERED",
        }
        assert transport.head_calls == []
        assert transport.get_calls == []
        _assert_no_records_created(sandbox.transport_record_path, sandbox.raw_record_path)


def test_transport_identity_pin_mismatch_from_malicious_lookup_refuses_before_real_get() -> None:
    """Finding #1 (independent review, the core regression guard): a
    caller-selected `published_archive_date_lookup`/`official_md5_lookup`
    callable -- the only place a confirmed-live `--execute` run imports
    non-production-owned code -- monkeypatching
    `type(transport).stream_get` DURING its own call (after
    `transport.head()` but before the real GET) is detected by the SECOND
    pin re-verification point, immediately before the real streamed GET,
    and the real (tampered) `stream_get` is never invoked."""
    _require_freeze_contract_symbols()
    module = require_module()
    with prospective_sandbox("transport-pin-mismatch-malicious-lookup") as sandbox:
        approval = build_approval_record(sandbox)
        transport = InjectedTransport(
            head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )
        pin = module.capture_transport_identity_pin(transport)
        original_stream_get = type(transport).stream_get

        def _malicious_published_date_lookup(url: str) -> dict[str, Any]:
            # Simulates arbitrary caller-selected code monkeypatching the
            # hard-wired transport's class -- e.g. to silently substitute a
            # different download source -- from inside a dynamically
            # resolved lookup callable.
            type(transport).stream_get = lambda self, u, chunk_bytes: (_ for _ in ()).throw(
                AssertionError("tampered stream_get must never be reached")
            )
            return {
                "published_archive_date": "2026-08-06",
                "source_identity": "ncbi-published-archive-index-2026-08",
            }

        try:
            result = execute_transport_and_raw_freeze(
                sandbox,
                approval_record=approval,
                transport=transport,
                published_archive_date_lookup=_malicious_published_date_lookup,
                official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
                transport_identity_pin=pin,
            )
        finally:
            type(transport).stream_get = original_stream_get
        assert result == {
            "stage_status": "BLOCKED",
            "terminal_outcome": "INVALID",
            "reason_code": "TRANSPORT_IDENTITY_TAMPERED",
        }
        assert transport.head_calls == [sandbox.exact_url]
        assert transport.get_calls == []


def test_implementation_freeze_executing_code_mismatch_is_rejected_independent_of_commit_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Finding #4 (independent review): even when `implementation_freeze`
    names a real, reachable commit whose committed tree content matches
    the declared `module_hashes` exactly, approval is still rejected if the
    bytes ACTUALLY loaded/executing in this process right now do not match
    that same declared hash -- proving approval is bound to the executing
    code, not merely a historical commit reference. Uses the dedicated,
    monkeypatchable `_read_executing_module_bytes` seam so this is testable
    independent of real git/commit state."""
    _require_freeze_contract_symbols()
    stop_error = require_exception("ProspectiveStopStateError")
    module = require_module()
    with prospective_sandbox("implementation-freeze-executing-code-mismatch") as sandbox:
        approval = build_approval_record(sandbox)

        def _tampered_read_executing_module_bytes(module_name: str) -> bytes:
            return b"this-is-not-the-approved-module-content"

        monkeypatch.setattr(module, "_read_executing_module_bytes", _tampered_read_executing_module_bytes)
        with pytest.raises(stop_error) as exc:
            validate_pre_data_approval(sandbox, approval_record=approval, first_archive_get_at=None)
        assert_stop_state(exc.value, "PRE_DATA_IMPLEMENTATION_NOT_READY")
        reason = str(getattr(exc.value, "reason", ""))
        assert "actually executing" in reason.lower() or "does not match the code" in reason.lower()


def test_toctou_overlay_mutation_between_head_and_get_is_invalid() -> None:
    _require_freeze_contract_symbols()
    with prospective_sandbox("toctou-overlay") as sandbox:
        approval = build_approval_record(sandbox)

        def _mutate_overlay() -> None:
            sandbox.overlay_path.write_text(
                sandbox.overlay_path.read_text(encoding="utf-8") + "\n# mutated-mid-run\n",
                encoding="utf-8",
            )

        transport = InjectedTransport(
            head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
            on_get_start=_mutate_overlay,
        )
        result = execute_transport_and_raw_freeze(
            sandbox,
            approval_record=approval,
            transport=transport,
            published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
            official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
        )
        assert result["terminal_outcome"] == "INVALID"
        assert result["reason_code"] == "OVERLAY_MUTATED_DURING_RUN"


def test_runtime_boundary_function_uses_adr0008_identity_dimensions() -> None:
    _require_freeze_contract_symbols()
    check_runtime = require_api("assert_runtime_boundary")
    invalid_error = require_exception("ProspectiveInvalidStateError")
    valid_runtime = {
        "worker_designation": "adr-0008-designated-x64-worker",
        "worker_arch": "x86_64",
        "bias_commit": "ade13f206f3e2c2efe3ec92715d974645fc8da8f",
        "nirvana_banner": "3.18.1-0-g05f88047",
        "resource_manifest_sha256": "1" * 64,
    }
    check_runtime(runtime_identity=valid_runtime)
    for bad in (
        {**valid_runtime, "worker_arch": "arm64"},
        {**valid_runtime, "worker_designation": "other-worker"},
        {**valid_runtime, "bias_commit": "0" * 40},
        {**valid_runtime, "nirvana_banner": "3.18.1"},
        {**valid_runtime, "resource_manifest_sha256": "broken"},
    ):
        with pytest.raises(invalid_error) as exc:
            check_runtime(runtime_identity=bad)
        assert getattr(exc.value, "code", None) == "INVALID"


def test_validate_pre_data_approval_closed_schema_and_non_vacuous_values() -> None:
    _require_freeze_contract_symbols()
    stop_error = require_exception("ProspectiveStopStateError")
    with prospective_sandbox("validate-approval") as sandbox:
        approval = build_approval_record(sandbox)
        validated = validate_pre_data_approval(sandbox, approval_record=approval, first_archive_get_at=None)
        assert validated["decision"] == "APPROVED_PRE_DATA"
        assert validated["registration"]["canonical_lf_sha256"] == canonical_lf_sha256_path(sandbox.spec_path)
        assert validated["overlay"]["canonical_lf_sha256"] == canonical_lf_sha256_path(sandbox.overlay_path)
        assert validated["scope"]["allow_substitute_archive"] is False
        assert validated["pre_data_access_attestation"]["archive_content_downloaded"] is False

        invalid_cases = [
            (_mutate_approval(approval, approver="@wrong"), "PRE_DATA_REVIEW_REQUIRED", None),
            (_mutate_approval(approval, decision="REJECTED_PRE_DATA"), "PRE_DATA_REJECTED", None),
            (_mutate_approval(approval, add_field=("extra", 1)), "PRE_DATA_REVIEW_REQUIRED", None),
            (_mutate_approval(approval, scope_updates={"allow_substitute_archive": True}), "PRE_DATA_REVIEW_REQUIRED", None),
            (_mutate_approval(approval, approved_at="2026-08-29T11:00:00Z"), "PRE_DATA_DRIFT", "2026-08-29T10:00:00Z"),
        ]
        for mutated, expected_stop, first_get_at in invalid_cases:
            with pytest.raises(stop_error) as exc:
                validate_pre_data_approval(
                    sandbox,
                    approval_record=mutated,
                    first_archive_get_at=first_get_at,
                )
            assert_stop_state(exc.value, expected_stop)


def test_transport_record_dotdot_escape_is_invalid_and_writes_nowhere() -> None:
    _require_freeze_contract_symbols()
    with prospective_sandbox("transport-dotdot-escape") as sandbox:
        approval = build_approval_record(sandbox)
        escaped_transport_path = sandbox.repo_root / ".." / "escaped-transport-freeze.json"
        outside_candidate = escaped_transport_path.resolve()
        assert not outside_candidate.exists()
        transport = InjectedTransport(
            head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )
        result = execute_transport_and_raw_freeze(
            sandbox,
            approval_record=approval,
            transport=transport,
            published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
            official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
            transport_record_path=escaped_transport_path,
        )
        assert result["terminal_outcome"] == "INVALID"
        assert isinstance(result.get("reason_code"), str) and result["reason_code"]
        assert transport.head_calls == []
        assert transport.get_calls == []
        assert not outside_candidate.exists()
        _assert_no_records_created(sandbox.raw_record_path)


def test_malicious_dataset_filename_traversal_is_invalid_and_never_downloaded() -> None:
    _require_freeze_contract_symbols()
    with prospective_sandbox("filename-traversal-boundary") as sandbox:
        _replace_once_in_file(
            sandbox.spec_path,
            "\n  filename: variant_summary_2026-08.txt.gz",
            "\n  filename: ../escaped-raw-archive.txt.gz",
        )
        approval = build_approval_record(sandbox)
        transport = InjectedTransport(
            head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )
        result = execute_transport_and_raw_freeze(
            sandbox,
            approval_record=approval,
            transport=transport,
            published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
            official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
        )
        assert result["terminal_outcome"] == "INVALID"
        assert isinstance(result.get("reason_code"), str) and result["reason_code"]
        assert transport.get_calls == []
        assert not (sandbox.external_root / "escaped-raw-archive.txt.gz").exists()
        assert _files_under(sandbox.external_root) == []
        _assert_no_records_created(sandbox.raw_record_path)


def test_stream_aborts_on_first_content_length_overflow_and_cleans_destination() -> None:
    _require_freeze_contract_symbols()
    with prospective_sandbox("stream-overflow-abort") as sandbox:
        approval = build_approval_record(sandbox)
        expected_len = len(sandbox.archive_bytes)
        first_half = sandbox.archive_bytes[: expected_len // 2]
        second_half = sandbox.archive_bytes[expected_len // 2 :]
        overflow_chunk = b"overflow!"
        tail_chunks = [b"tail-1", b"tail-2", b"tail-3"]

        class _OverflowTransport:
            def __init__(self) -> None:
                self.head_calls: list[str] = []
                self.get_calls: list[tuple[str, int]] = []
                self.tail_chunks_consumed = 0

            def head(self, url: str) -> dict[str, Any]:
                self.head_calls.append(url)
                return make_head_payload(sandbox)

            def stream_get(self, url: str, chunk_bytes: int):
                self.get_calls.append((url, chunk_bytes))
                for idx, chunk in enumerate([first_half, second_half, overflow_chunk, *tail_chunks]):
                    if idx >= 3:
                        self.tail_chunks_consumed += 1
                    yield chunk

        transport = _OverflowTransport()
        result = execute_transport_and_raw_freeze(
            sandbox,
            approval_record=approval,
            transport=transport,
            published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
            official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
        )
        assert result["terminal_outcome"] == "BLOCKED_DATA"
        assert result["reason_code"] == "RAW_LENGTH_MISMATCH"
        assert transport.tail_chunks_consumed == 0
        assert _files_under(sandbox.external_root) == []
        _assert_no_records_created(sandbox.raw_record_path)


@pytest.mark.parametrize(
    ("case_id", "mutate_records"),
    (
        (
            "transport-link-mismatch",
            lambda transport_record, raw_record: raw_record.__setitem__("transport_record_content_hash", "f" * 64),
        ),
        (
            "registration-id-mismatch",
            lambda transport_record, raw_record: raw_record.__setitem__("registration_id", "drifted-registration-id"),
        ),
        (
            "run-scope-id-mismatch",
            lambda transport_record, raw_record: raw_record.__setitem__("run_scope_id", "drifted-run-scope-id"),
        ),
    ),
)
def test_restart_reuse_requires_chain_and_identity_match(
    case_id: str,
    mutate_records: Callable[[dict[str, Any], dict[str, Any]], None],
) -> None:
    _require_freeze_contract_symbols()
    with prospective_sandbox(f"reuse-identity-{case_id}") as sandbox:
        approval = build_approval_record(sandbox)
        first = execute_transport_and_raw_freeze(
            sandbox,
            approval_record=approval,
            transport=InjectedTransport(
                head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
                body_by_url={sandbox.exact_url: sandbox.archive_bytes},
            ),
            published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
            official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
        )
        assert first["stage_status"] == "TRANSPORT_AND_RAW_FROZEN"

        transport_record = assert_record_content_hash(sandbox.transport_record_path)
        raw_record = assert_record_content_hash(sandbox.raw_record_path)
        mutate_records(transport_record, raw_record)
        transport_record["content_hash"] = canonical_json_content_hash(transport_record)
        raw_record["content_hash"] = canonical_json_content_hash(raw_record)
        sandbox.transport_record_path.write_text(
            json.dumps(transport_record, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        sandbox.raw_record_path.write_text(
            json.dumps(raw_record, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

        second_transport = InjectedTransport(
            head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )
        second = execute_transport_and_raw_freeze(
            sandbox,
            approval_record=approval,
            transport=second_transport,
            published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
            official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
        )
        assert second["terminal_outcome"] == "INVALID"
        assert isinstance(second.get("reason_code"), str) and second["reason_code"]
        assert second.get("idempotent_reuse") is not True
        assert second_transport.head_calls == []
        assert second_transport.get_calls == []


@pytest.mark.parametrize(
    ("case_id", "mutate"),
    (
        (
            "overlay-required-registration-id-drift",
            lambda sandbox: _replace_once_in_file(
                sandbox.overlay_path,
                "registration_id: \"clinvar-2026-08-amendment-v3\"",
                "registration_id: \"clinvar-2026-08-amendment-v3-drift\"",
            ),
        ),
        (
            "overlay-base-config-hash-drift",
            lambda sandbox: _replace_once_in_file(
                sandbox.overlay_path,
                "base_config_canonical_lf_sha256: \"45358c2e66d09d8ba32937b1d2751659f382a8444679fdd0244bbde3b63f7206\"",
                "base_config_canonical_lf_sha256: \"0000000000000000000000000000000000000000000000000000000000000000\"",
            ),
        ),
        (
            "overlay-exact-url-alias",
            lambda sandbox: _replace_once_in_file(
                sandbox.overlay_path,
                "exact_archive_url: \"https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/archive/variant_summary_2026-08.txt.gz\"",
                "exact_archive_url: \"https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/archive/variant_summary_2026-08-alias.txt.gz\"",
            ),
        ),
        (
            "dataset-registration-exact-url-alias",
            lambda sandbox: _replace_once_in_file(
                sandbox.spec_path,
                "  exact_url: https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/archive/variant_summary_2026-08.txt.gz",
                "  exact_url: https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/archive/variant_summary_2026-08-alias.txt.gz",
            ),
        ),
        (
            "request-url-must-equal-alias",
            lambda sandbox: _replace_once_in_file(
                sandbox.spec_path,
                "    request_url_must_equal: https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/archive/variant_summary_2026-08.txt.gz",
                "    request_url_must_equal: https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/archive/variant_summary_2026-08-alias.txt.gz",
            ),
        ),
    ),
)
def test_execution_rejects_overlay_required_value_or_url_coherence_drift_before_network(
    case_id: str,
    mutate: Callable[[Any], None],
) -> None:
    _require_freeze_contract_symbols()
    alias_url = "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/archive/variant_summary_2026-08-alias.txt.gz"
    with prospective_sandbox(f"overlay-url-coherence-{case_id}") as sandbox:
        mutate(sandbox)
        approval = build_approval_record(sandbox)
        head_payload = make_head_payload(sandbox)
        transport = InjectedTransport(
            head_by_url={
                sandbox.exact_url: head_payload,
                alias_url: {**head_payload, "final_url": sandbox.required_final_url},
            },
            body_by_url={sandbox.exact_url: sandbox.archive_bytes, alias_url: sandbox.archive_bytes},
        )
        result = execute_transport_and_raw_freeze(
            sandbox,
            approval_record=approval,
            transport=transport,
            published_archive_date_lookup=InjectedLookup(
                {
                    sandbox.exact_url: {
                        "published_archive_date": "2026-08-06",
                        "source_identity": "ncbi-published-archive-index-2026-08",
                    },
                    alias_url: {
                        "published_archive_date": "2026-08-06",
                        "source_identity": "ncbi-published-archive-index-2026-08",
                    },
                }
            ),
            official_md5_lookup=InjectedLookup(
                {
                    sandbox.exact_url: {
                        "official_md5": None,
                        "upstream_checksum_available": False,
                        "source_identity": "ncbi-clinvar-monthly-archive-index",
                        "unavailable_reason": "not published",
                        "verification_mode": "EXACT_URL_HEAD_CONTINUITY_PLUS_LOCAL_SHA256_MD5",
                    },
                    alias_url: {
                        "official_md5": None,
                        "upstream_checksum_available": False,
                        "source_identity": "ncbi-clinvar-monthly-archive-index",
                        "unavailable_reason": "not published",
                        "verification_mode": "EXACT_URL_HEAD_CONTINUITY_PLUS_LOCAL_SHA256_MD5",
                    },
                }
            ),
        )
        assert result["terminal_outcome"] == "INVALID"
        assert isinstance(result.get("reason_code"), str) and result["reason_code"]
        assert transport.head_calls == []
        assert transport.get_calls == []
        _assert_no_records_created(sandbox.transport_record_path, sandbox.raw_record_path)


def test_execute_path_never_consults_merge_overlay_or_scoring_semantics() -> None:
    """Finding #4 (acquisition/scoring-config boundary): `execute_transport_
    and_raw_freeze` (ADR-0022 stages 1-2) must NEVER call
    `merge_prospective_overlay` and must NEVER verify scoring-semantics or
    base-eval-config hashes -- that verification belongs solely to
    `merge_prospective_overlay`, invoked only for ADR-0022 stage 3+
    scoring. This replaces the historical (pre-fix) test that required the
    opposite behavior."""
    _require_freeze_contract_symbols()
    module = require_module()

    def _forbidden_merge(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        pytest.fail("execute_transport_and_raw_freeze must never call merge_prospective_overlay")

    original = getattr(module, "merge_prospective_overlay")
    setattr(module, "merge_prospective_overlay", _forbidden_merge)
    try:
        with prospective_sandbox("execute-never-merges-overlay") as sandbox:
            approval = build_approval_record(sandbox)
            transport = InjectedTransport(
                head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
                body_by_url={sandbox.exact_url: sandbox.archive_bytes},
            )
            result = execute_transport_and_raw_freeze(
                sandbox,
                approval_record=approval,
                transport=transport,
                published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
                official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
            )
            assert result["stage_status"] == "TRANSPORT_AND_RAW_FROZEN"
    finally:
        setattr(module, "merge_prospective_overlay", original)


def test_execute_transport_and_raw_freeze_signature_has_no_base_eval_config_path_param() -> None:
    """`execute_transport_and_raw_freeze` must accept no
    `base_eval_config_path` parameter at all -- acquisition never reads a
    base eval config."""
    _require_freeze_contract_symbols()
    module = require_module()
    import inspect

    signature = inspect.signature(module.execute_transport_and_raw_freeze)
    assert "base_eval_config_path" not in signature.parameters


def test_pre_data_approval_record_has_no_scoring_semantics_projection_field() -> None:
    """`pre_data_approval` records no longer carry
    `scoring_semantics_projection_sha256` -- that concern moved entirely to
    `merge_prospective_overlay` (stage 3+ scoring), never pre-data
    acquisition approval."""
    _require_freeze_contract_symbols()
    with prospective_sandbox("pre-data-approval-no-scoring-semantics-field") as sandbox:
        approval = build_approval_record(sandbox)
        assert "scoring_semantics_projection_sha256" not in approval
        validated = validate_pre_data_approval(sandbox, approval_record=approval)
        assert "scoring_semantics_projection_sha256" not in validated


@pytest.mark.parametrize("target_record", ("transport", "raw"))
def test_non_utf8_existing_freeze_record_is_typed_invalid(target_record: str) -> None:
    _require_freeze_contract_symbols()
    with prospective_sandbox(f"non-utf8-existing-{target_record}") as sandbox:
        approval = build_approval_record(sandbox)
        first = execute_transport_and_raw_freeze(
            sandbox,
            approval_record=approval,
            transport=InjectedTransport(
                head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
                body_by_url={sandbox.exact_url: sandbox.archive_bytes},
            ),
            published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
            official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
        )
        assert first["stage_status"] == "TRANSPORT_AND_RAW_FROZEN"
        target_path = sandbox.transport_record_path if target_record == "transport" else sandbox.raw_record_path
        target_path.write_bytes(b"\xff\xfe\xfa")
        second_transport = InjectedTransport(
            head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )
        second = execute_transport_and_raw_freeze(
            sandbox,
            approval_record=approval,
            transport=second_transport,
            published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
            official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
        )
        assert second["terminal_outcome"] == "INVALID"
        assert isinstance(second.get("reason_code"), str) and second["reason_code"]
        assert second_transport.head_calls == []
        assert second_transport.get_calls == []


@pytest.mark.parametrize(
    ("case_id", "mutate_during_get"),
    (
        ("overlay-deleted", lambda sandbox: sandbox.overlay_path.unlink()),
        (
            "spec-unreadable",
            lambda sandbox: (
                sandbox.spec_path.unlink(),
                sandbox.spec_path.mkdir(parents=True, exist_ok=False),
            ),
        ),
    ),
)
def test_overlay_or_spec_unreadable_during_get_is_typed_invalid_and_cleans_raw_artifacts(
    case_id: str,
    mutate_during_get: Callable[[Any], Any],
) -> None:
    _require_freeze_contract_symbols()
    invalid_error = require_exception("ProspectiveInvalidStateError")
    with prospective_sandbox(f"spec-overlay-unreadable-{case_id}") as sandbox:
        approval = build_approval_record(sandbox)
        transport = InjectedTransport(
            head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
            on_get_start=lambda: mutate_during_get(sandbox),
        )
        caught: BaseException | None = None
        result: dict[str, Any] | None = None
        try:
            result = execute_transport_and_raw_freeze(
                sandbox,
                approval_record=approval,
                transport=transport,
                published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
                official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
            )
        except BaseException as exc:  # noqa: BLE001
            caught = exc

        if caught is None:
            assert result is not None
            assert result["terminal_outcome"] == "INVALID"
            assert isinstance(result.get("reason_code"), str) and result["reason_code"]
        elif isinstance(caught, invalid_error):
            assert getattr(caught, "code", None) == "INVALID"
            reason_text = getattr(caught, "reason", "")
            assert isinstance(reason_text, str) and reason_text.strip()
        else:  # pragma: no cover - this is the regression condition under checker findings
            pytest.fail(f"must surface typed INVALID on spec/overlay unreadability during GET, got {type(caught).__name__}")

        assert not sandbox.raw_record_path.exists()
        assert _files_under(sandbox.external_root) == []


def test_executor_rejects_approval_after_recorded_get_time_without_external_timestamp() -> None:
    _require_freeze_contract_symbols()
    stop_error = require_exception("ProspectiveStopStateError")
    with prospective_sandbox("internal-first-get-time-check") as sandbox:
        approval = build_approval_record(sandbox)
        first_transport = InjectedTransport(
            head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )
        first = execute_transport_and_raw_freeze(
            sandbox,
            approval_record=approval,
            transport=first_transport,
            published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
            official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
        )
        assert first["stage_status"] == "TRANSPORT_AND_RAW_FROZEN"

        stale_approval = _mutate_approval(approval, approved_at="2099-01-01T00:00:00Z")
        second_transport = InjectedTransport(
            head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )
        with pytest.raises(stop_error) as exc:
            execute_transport_and_raw_freeze(
                sandbox,
                approval_record=stale_approval,
                transport=second_transport,
                published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
                official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
            )
        assert_stop_state(exc.value, "PRE_DATA_DRIFT")
        assert second_transport.head_calls == []
        assert second_transport.get_calls == []


def test_transport_record_binds_pre_data_approval_identity_and_get_timeline() -> None:
    _require_freeze_contract_symbols()
    with prospective_sandbox("transport-record-approval-binding") as sandbox:
        approval = build_approval_record(sandbox)
        result = execute_transport_and_raw_freeze(
            sandbox,
            approval_record=approval,
            transport=InjectedTransport(
                head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
                body_by_url={sandbox.exact_url: sandbox.archive_bytes},
            ),
            published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
            official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
        )
        assert result["stage_status"] == "TRANSPORT_AND_RAW_FROZEN"
        transport_record = assert_record_content_hash(sandbox.transport_record_path)
        expected_approval_hash = canonical_json_content_hash(approval)
        assert transport_record["approval_content_hash"] == expected_approval_hash
        assert transport_record["approval_approver"] == approval["approver"]
        assert transport_record["approval_approved_at"] == approval["approved_at"]
        assert isinstance(transport_record.get("first_archive_get_at"), str) and transport_record["first_archive_get_at"]
        timeline = transport_record.get("timeline")
        assert isinstance(timeline, list) and timeline
        event_names = {item.get("event") for item in timeline if isinstance(item, dict)}
        assert "approval_verified" in event_names
        assert "archive_get_started" in event_names


@pytest.mark.parametrize(
    ("case_id", "mutate"),
    (
        (
            "wrong-approval-schema",
            lambda approval: {**approval, "schema": "raptor.eval.pre_data_approval.v9"},
        ),
    ),
)
def test_validate_pre_data_approval_rejects_schema_drift_as_pre_data_drift(
    case_id: str,
    mutate: Callable[[dict[str, Any]], dict[str, Any]],
) -> None:
    _require_freeze_contract_symbols()
    stop_error = require_exception("ProspectiveStopStateError")
    with prospective_sandbox(f"approval-schema-drift-{case_id}") as sandbox:
        approval = build_approval_record(sandbox)
        with pytest.raises(stop_error) as exc:
            validate_pre_data_approval(sandbox, approval_record=mutate(approval), first_archive_get_at=None)
        assert_stop_state(exc.value, "PRE_DATA_DRIFT")


@pytest.mark.parametrize(
    ("case_id", "mutate"),
    (
        (
            "wrong-schema",
            lambda approval: {**approval, "schema": "raptor.eval.scoring_stage_approval.v9"},
        ),
        (
            "wrong-registration-id",
            lambda approval: {**approval, "registration_id": "some-other-registration"},
        ),
        (
            "blank-approver",
            lambda approval: {**approval, "approver": "  "},
        ),
        (
            "blank-approved-at",
            lambda approval: {**approval, "approved_at": ""},
        ),
        (
            "invalid-approved-at",
            lambda approval: {**approval, "approved_at": "not-a-timestamp"},
        ),
        (
            "x64-worker-arch-invalid",
            lambda approval: {**approval, "x64_freeze": {**approval["x64_freeze"], "worker_arch": "arm64"}},
        ),
        (
            "x64-bias-commit-invalid",
            lambda approval: {**approval, "x64_freeze": {**approval["x64_freeze"], "bias_commit": "0" * 40}},
        ),
        (
            "x64-resource-manifest-invalid",
            lambda approval: {
                **approval,
                "x64_freeze": {**approval["x64_freeze"], "resource_manifest_sha256": "broken"},
            },
        ),
        (
            "x64-freeze-missing-key",
            lambda approval: {
                **approval,
                "x64_freeze": {k: v for k, v in approval["x64_freeze"].items() if k != "worker_arch"},
            },
        ),
    ),
)
def test_validate_scoring_stage_approval_rejects_schema_or_x64_freeze_drift_as_invalid(
    case_id: str,
    mutate: Callable[[dict[str, Any]], dict[str, Any]],
) -> None:
    """`validate_scoring_stage_approval` is the SEPARATE, LATER ADR-0022
    stage 4 gate. Any schema, registration_id, approver/timestamp, or
    x64_freeze identity breach raises `ProspectiveInvalidStateError`
    (`.code == "INVALID"`) -- never a `PRE_DATA_*` stop state."""
    _require_freeze_contract_symbols()
    invalid_error = require_exception("ProspectiveInvalidStateError")
    with prospective_sandbox(f"scoring-stage-schema-drift-{case_id}") as sandbox:
        approval = build_scoring_stage_approval_record(sandbox)
        with pytest.raises(invalid_error) as exc:
            validate_scoring_stage_approval(sandbox, approval_record=mutate(approval))
        assert exc.value.code == "INVALID"


def test_validate_scoring_stage_approval_accepts_valid_record() -> None:
    _require_freeze_contract_symbols()
    with prospective_sandbox("scoring-stage-valid") as sandbox:
        approval = build_scoring_stage_approval_record(sandbox)
        result = validate_scoring_stage_approval(sandbox, approval_record=approval)
        assert result["schema"] == "raptor.eval.scoring_stage_approval.v1"
        assert result["decision"] == "APPROVED_SCORING_STAGE"
        module = require_module()
        expected_digest = module.compute_resource_manifest_sha256(sandbox.resource_manifest_checksums_dir)
        assert result["x64_freeze"] == runtime_identity_ok(resource_manifest_sha256=expected_digest)


@pytest.mark.parametrize(
    ("case_id", "mutate"),
    (
        ("rejected-decision", lambda approval: {**approval, "decision": "REJECTED_SCORING_STAGE"}),
        ("unknown-decision", lambda approval: {**approval, "decision": "APPROVED"}),
        ("missing-decision", lambda approval: {k: v for k, v in approval.items() if k != "decision"}),
        ("wrong-approver", lambda approval: {**approval, "approver": "@someone-else"}),
    ),
)
def test_validate_scoring_stage_approval_requires_explicit_decision_and_exact_approver(
    case_id: str,
    mutate: Callable[[dict[str, Any]], dict[str, Any]],
) -> None:
    """Finding #1 (anti-fabrication): `validate_scoring_stage_approval`
    requires the explicit `APPROVED_SCORING_STAGE` decision (a recorded
    `REJECTED_SCORING_STAGE` is rejected distinctly from an unknown/missing
    decision) and the exact `approver_required` from the binding spec --
    never merely a well-formed/non-blank string."""
    _require_freeze_contract_symbols()
    invalid_error = require_exception("ProspectiveInvalidStateError")
    with prospective_sandbox(f"scoring-stage-decision-approver-{case_id}") as sandbox:
        approval = build_scoring_stage_approval_record(sandbox)
        with pytest.raises(invalid_error) as exc:
            validate_scoring_stage_approval(sandbox, approval_record=mutate(approval))
        assert exc.value.code == "INVALID"


def test_validate_scoring_stage_approval_requires_approval_before_first_scoring_execution() -> None:
    """Finding #1: an `approved_at` that is not strictly before
    `first_scoring_execution_at` is rejected -- mirrors the pre_data
    approval-vs-first-GET timing pattern, applied to the scoring-stage
    gate's approval-vs-first-execution timing."""
    _require_freeze_contract_symbols()
    invalid_error = require_exception("ProspectiveInvalidStateError")
    with prospective_sandbox("scoring-stage-timing") as sandbox:
        approval = build_scoring_stage_approval_record(sandbox, approved_at="2026-08-29T10:00:00Z")
        with pytest.raises(invalid_error) as exc:
            validate_scoring_stage_approval(
                sandbox,
                approval_record=approval,
                first_scoring_execution_at="2026-08-29T09:00:00Z",
            )
        assert exc.value.code == "INVALID"
        # A first-execution timestamp strictly AFTER approval is accepted.
        validate_scoring_stage_approval(
            sandbox,
            approval_record=approval,
            first_scoring_execution_at="2026-08-29T11:00:00Z",
        )


@pytest.mark.parametrize(
    "fabricated_digest",
    ("0" * 64, "f" * 64, "1234567890abcdef" * 4),
)
def test_validate_scoring_stage_approval_rejects_fabricated_digest_that_does_not_match_recomputation(
    fabricated_digest: str,
) -> None:
    """Finding #1 (the core anti-fabrication requirement): a claimed
    `resource_manifest_sha256` that is well-formed 64-lowercase-hex --
    including an all-zero digest -- MUST NOT pass unless it exactly equals
    the value independently RECOMPUTED from the real manifest files. This
    is the central regression guard for the reviewed vulnerability (a
    merely well-formed claimed digest previously always passed FORMAT-only
    validation)."""
    _require_freeze_contract_symbols()
    invalid_error = require_exception("ProspectiveInvalidStateError")
    with prospective_sandbox("scoring-stage-fabricated-digest") as sandbox:
        approval = build_scoring_stage_approval_record(
            sandbox, x64_freeze_overrides={"resource_manifest_sha256": fabricated_digest}
        )
        with pytest.raises(invalid_error) as exc:
            validate_scoring_stage_approval(sandbox, approval_record=approval)
        assert exc.value.code == "INVALID"


def test_validate_scoring_stage_approval_rejects_when_observed_identity_probe_disagrees_with_claim() -> None:
    """Finding #2 (independent review): a claimed `x64_freeze` that matches
    the ADR-0008 pinned constants exactly is still rejected when the
    INDEPENDENTLY OBSERVED identity (via a probe override simulating a
    genuine, non-matching host observation -- never a caller-supplied
    plain mapping) disagrees. The claim is never trusted on its own; only
    the observation is."""
    _require_freeze_contract_symbols()
    invalid_error = require_exception("ProspectiveInvalidStateError")
    with prospective_sandbox("scoring-stage-observed-probe-disagrees") as sandbox:
        approval = build_scoring_stage_approval_record(sandbox)
        with pytest.raises(invalid_error) as exc:
            validate_scoring_stage_approval(sandbox, approval_record=approval, worker_arch_probe=lambda: "arm64")
        assert exc.value.code == "INVALID"


def test_validate_scoring_stage_approval_rejects_pinned_literals_on_non_designated_runtime_via_real_default_probes() -> None:
    """Finding #2 (independent review, the central regression guard): a
    claimed `x64_freeze` that recites the EXACT pinned worker/BIAS/Nirvana
    literal constants still fails closed when validated with the REAL
    production default probes (no override at all for
    worker_designation/worker_arch/bias_commit/nirvana_banner) on this
    non-designated WSL2 dev/test host -- because those defaults genuinely
    read the (absent) ADR-0008 marker files under
    `DESIGNATED_X64_WORKER_ROOT` and observe non-matching
    `UNOBSERVABLE:`-prefixed sentinel values, which can never equal a
    caller's claimed literal no matter how well-formed. Only
    `resource_manifest_location_probe` is overridden here (pointed at the
    sandbox's own fixture manifests, a test-only override), so the digest
    recomputation itself succeeds and this test isolates the
    worker-designation/BIAS-commit/Nirvana-banner observation failure
    specifically -- proving a static pinned literal supplied on a
    non-designated runtime cannot pass."""
    _require_freeze_contract_symbols()
    invalid_error = require_exception("ProspectiveInvalidStateError")
    fn = require_api("validate_scoring_stage_approval")
    with prospective_sandbox("scoring-stage-real-default-probes-non-designated") as sandbox:
        approval = build_scoring_stage_approval_record(sandbox)
        with pytest.raises(invalid_error) as exc:
            fn(
                registration_id=sandbox.spec["registration"]["id"],
                registration_spec_path=sandbox.spec_path,
                approval_record=approval,
                allowed_repo_root=sandbox.repo_root,
                first_scoring_execution_at="2026-08-29T12:00:00Z",
                resource_manifest_location_probe=lambda: sandbox.resource_manifest_checksums_dir,
            )
        assert exc.value.code == "INVALID"


def test_validate_scoring_stage_approval_requires_mandatory_immutable_first_scoring_execution_timestamp() -> None:
    """Finding #3 (independent review): `first_scoring_execution_at` is a
    MANDATORY, immutable timestamp -- never optional. Absent/blank,
    malformed, or future-dated all fail closed, in addition to the
    already-covered at/after-`approved_at` mistiming case."""
    _require_freeze_contract_symbols()
    invalid_error = require_exception("ProspectiveInvalidStateError")
    with prospective_sandbox("scoring-stage-timestamp-mandatory") as sandbox:
        approval = build_scoring_stage_approval_record(sandbox, approved_at="2026-08-29T10:00:00Z")
        for missing_value in (None, "", "   "):
            with pytest.raises(invalid_error) as exc:
                validate_scoring_stage_approval(sandbox, approval_record=approval, first_scoring_execution_at=missing_value)
            assert exc.value.code == "INVALID"
        with pytest.raises(invalid_error) as exc:
            validate_scoring_stage_approval(
                sandbox, approval_record=approval, first_scoring_execution_at="not-a-timestamp"
            )
        assert exc.value.code == "INVALID"
        with pytest.raises(invalid_error) as exc:
            validate_scoring_stage_approval(
                sandbox, approval_record=approval, first_scoring_execution_at="2999-01-01T00:00:00Z"
            )
        assert exc.value.code == "INVALID"


def test_validate_scoring_stage_approval_rejects_when_recomputed_manifest_bytes_changed() -> None:
    """The claimed digest is checked against a digest RECOMPUTED from the
    manifest files at validation time -- if those files' bytes change after
    the approval record was built (drift), the approval no longer matches
    and is rejected, even though the claimed digest itself never changed."""
    _require_freeze_contract_symbols()
    invalid_error = require_exception("ProspectiveInvalidStateError")
    with prospective_sandbox("scoring-stage-manifest-drift") as sandbox:
        approval = build_scoring_stage_approval_record(sandbox)
        # Mutate one pinned manifest file's bytes AFTER the approval was
        # built against the original bytes.
        module = require_module()
        _entry_id, filename = module.RESOURCE_MANIFEST_ENTRIES[0]
        target = sandbox.resource_manifest_checksums_dir / filename
        target.write_bytes(target.read_bytes() + b"\x00mutated")
        with pytest.raises(invalid_error) as exc:
            validate_scoring_stage_approval(sandbox, approval_record=approval)
        assert exc.value.code == "INVALID"


def test_validate_scoring_stage_approval_rejects_observed_identity_that_fails_pinned_constants() -> None:
    """Even when the CLAIMED `x64_freeze` is internally self-consistent, an
    observed identity (via probe override) that itself does not match the
    ADR-0008 pinned worker/BIAS/Nirvana constants is rejected --
    `assert_runtime_boundary` is applied to the observed/recomputed
    identity, not only the equality cross-check."""
    _require_freeze_contract_symbols()
    invalid_error = require_exception("ProspectiveInvalidStateError")
    with prospective_sandbox("scoring-stage-bad-observed-constants") as sandbox:
        approval = build_scoring_stage_approval_record(sandbox, x64_freeze_overrides={"worker_arch": "arm64"})
        with pytest.raises(invalid_error) as exc:
            validate_scoring_stage_approval(sandbox, approval_record=approval, worker_arch_probe=lambda: "arm64")
        assert exc.value.code == "INVALID"


def test_symlink_dotdot_escape_is_invalid_destination_outside_allowed_root_and_no_outside_write() -> None:
    _require_freeze_contract_symbols()
    with prospective_sandbox("symlink-dotdot-escape") as sandbox:
        if not _can_create_symlink(sandbox.root):
            pytest.skip("symlink creation unsupported in this environment")
        approval = build_approval_record(sandbox)
        allowed = sandbox.repo_root / "allowed"
        allowed.mkdir(parents=True, exist_ok=True)
        outside_inner = sandbox.root / "outside" / "inner"
        outside_inner.mkdir(parents=True, exist_ok=True)
        evil_link = allowed / "evil-link"
        os.symlink(outside_inner, evil_link)

        destination = allowed / "evil-link" / ".." / "pwned.json"
        outside_candidate = outside_inner.parent / "pwned.json"
        inside_lexical_candidate = allowed / "pwned.json"
        assert not outside_candidate.exists()
        assert not inside_lexical_candidate.exists()

        transport = InjectedTransport(
            head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )
        result = execute_transport_and_raw_freeze(
            sandbox,
            approval_record=approval,
            transport=transport,
            published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
            official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
            transport_record_path=destination,
        )
        assert result["terminal_outcome"] == "INVALID"
        assert result["reason_code"] == "DESTINATION_OUTSIDE_ALLOWED_ROOT"
        assert transport.head_calls == []
        assert transport.get_calls == []
        assert not outside_candidate.exists()
        assert not inside_lexical_candidate.exists()
        _assert_no_records_created(sandbox.raw_record_path)


def test_out_of_root_record_peek_data_never_preempts_destination_invalid() -> None:
    _require_freeze_contract_symbols()
    stop_error = require_exception("ProspectiveStopStateError")
    with prospective_sandbox("outside-peek-never-preempts-boundary") as sandbox:
        approval = build_approval_record(sandbox)
        outside_transport_record = sandbox.root / "outside-transport-record.json"
        outside_transport_record.write_text(
            json.dumps(
                {
                    "first_archive_get_at": "2026-08-29T09:00:00Z",
                    "content_hash": "invalid",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        transport = InjectedTransport(
            head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )
        try:
            result = execute_transport_and_raw_freeze(
                sandbox,
                approval_record=approval,
                transport=transport,
                published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
                official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
                transport_record_path=outside_transport_record,
            )
        except stop_error as exc:
            pytest.fail(f"destination boundary must win before first_archive_get_at peek; got {exc!r}")
        assert result["terminal_outcome"] == "INVALID"
        assert result["reason_code"] == "DESTINATION_OUTSIDE_ALLOWED_ROOT"
        assert transport.head_calls == []
        assert transport.get_calls == []
        _assert_no_records_created(sandbox.raw_record_path)


def test_fifo_outside_allowed_root_returns_typed_invalid_without_hang_or_network() -> None:
    _require_freeze_contract_symbols()
    stop_error = require_exception("ProspectiveStopStateError")
    invalid_error = require_exception("ProspectiveInvalidStateError")
    with prospective_sandbox("fifo-outside-root-boundary") as sandbox:
        outside_dir = sandbox.root / "outside-fifo"
        outside_dir.mkdir(parents=True, exist_ok=True)
        fifo_supported, fifo_reason = _probe_fifo_capability(outside_dir)
        if not fifo_supported:
            pytest.skip(fifo_reason)
        fifo_path = outside_dir / "transport-record.fifo"
        os.mkfifo(fifo_path)

        transport = InjectedTransport(
            head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )
        result_box: dict[str, Any] = {}
        error_box: dict[str, BaseException] = {}

        def _run() -> None:
            try:
                result_box["value"] = execute_transport_and_raw_freeze(
                    sandbox,
                    approval_record=build_approval_record(sandbox),
                    transport=transport,
                    published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
                    official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
                    transport_record_path=fifo_path,
                )
            except BaseException as exc:  # noqa: BLE001
                error_box["value"] = exc

        worker = threading.Thread(target=_run, daemon=True)
        worker.start()
        worker.join(timeout=5)
        assert not worker.is_alive(), "executor hung on FIFO path instead of prompt boundary INVALID"
        if "value" in error_box:
            err = error_box["value"]
            if isinstance(err, stop_error):
                pytest.fail(f"boundary INVALID must preempt PRE_DATA stop-state logic; got {err!r}")
            if isinstance(err, invalid_error):
                assert getattr(err, "code", None) == "INVALID"
            else:
                raise err
        else:
            result = result_box["value"]
            assert result["terminal_outcome"] == "INVALID"
            assert result["reason_code"] == "DESTINATION_OUTSIDE_ALLOWED_ROOT"
        assert transport.head_calls == []
        assert transport.get_calls == []
        _assert_no_records_created(sandbox.transport_record_path, sandbox.raw_record_path)


def test_first_archive_get_at_trusted_only_after_valid_record_self_hash() -> None:
    _require_freeze_contract_symbols()
    stop_error = require_exception("ProspectiveStopStateError")
    invalid_error = require_exception("ProspectiveInvalidStateError")
    problems: list[str] = []

    with prospective_sandbox("peek-first-get-untrusted-with-bad-hash") as sandbox:
        approval = _mutate_approval(build_approval_record(sandbox), approved_at="2026-08-29T11:00:00Z")
        poisoned = {
            "first_archive_get_at": "2026-08-29T10:00:00Z",
            "content_hash": "bad-hash",
        }
        sandbox.transport_record_path.parent.mkdir(parents=True, exist_ok=True)
        poisoned_bytes = (json.dumps(poisoned, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        sandbox.transport_record_path.write_bytes(poisoned_bytes)
        transport = InjectedTransport(
            head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )
        caught: BaseException | None = None
        result: dict[str, Any] | None = None
        try:
            result = execute_transport_and_raw_freeze(
                sandbox,
                approval_record=approval,
                transport=transport,
                published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
                official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
            )
        except BaseException as exc:  # noqa: BLE001
            caught = exc

        if isinstance(caught, stop_error):
            problems.append(
                f"corrupt registered-path transport record must yield typed INVALID, not stop-state: {caught!r}"
            )
        elif isinstance(caught, invalid_error):
            if getattr(caught, "code", None) != "INVALID":
                problems.append(f"invalid exception must carry code INVALID, got {getattr(caught, 'code', None)!r}")
            reason_text = getattr(caught, "reason", "")
            if not (isinstance(reason_text, str) and reason_text.strip()):
                problems.append("invalid exception must carry a non-blank reason")
        elif caught is not None:
            problems.append(f"unexpected exception type for corrupt registered-path record: {type(caught).__name__}")
        else:
            if result is None:
                problems.append("executor returned neither result nor exception for corrupt registered-path record")
            else:
                if result.get("terminal_outcome") != "INVALID":
                    problems.append(
                        f"corrupt registered-path record must return terminal_outcome INVALID, got {result.get('terminal_outcome')!r}"
                    )
                if result.get("reason_code") != "TRANSPORT_RECORD_CORRUPT":
                    problems.append(
                        f"corrupt registered-path record must return reason TRANSPORT_RECORD_CORRUPT, got {result.get('reason_code')!r}"
                    )
        if transport.head_calls != []:
            problems.append(f"corrupt record path must stop before HEAD; observed {transport.head_calls!r}")
        if transport.get_calls != []:
            problems.append(f"corrupt record path must stop before GET; observed {transport.get_calls!r}")
        if sandbox.transport_record_path.read_bytes() != poisoned_bytes:
            problems.append("corrupt existing transport record must not be overwritten")
        if sandbox.raw_record_path.exists():
            problems.append("corrupt existing transport record must not produce a new raw record")

    with prospective_sandbox("peek-first-get-trusted-with-good-hash") as sandbox:
        approval = _mutate_approval(build_approval_record(sandbox), approved_at="2026-08-29T11:00:00Z")
        trusted = {"first_archive_get_at": "2026-08-29T10:00:00Z"}
        trusted["content_hash"] = canonical_json_content_hash(trusted)
        sandbox.transport_record_path.parent.mkdir(parents=True, exist_ok=True)
        sandbox.transport_record_path.write_text(
            json.dumps(trusted, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        transport = InjectedTransport(
            head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )
        with pytest.raises(stop_error) as exc:
            execute_transport_and_raw_freeze(
                sandbox,
                approval_record=approval,
                transport=transport,
                published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
                official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
            )
        assert_stop_state(exc.value, "PRE_DATA_DRIFT")
        assert transport.head_calls == []
        assert transport.get_calls == []
    if problems:
        pytest.fail("\n".join(problems))


def test_first_run_future_approval_is_pre_data_drift_before_any_network_or_record_write() -> None:
    _require_freeze_contract_symbols()
    stop_error = require_exception("ProspectiveStopStateError")
    with prospective_sandbox("future-approval-first-run") as sandbox:
        approval = build_approval_record(sandbox, approved_at="2099-01-01T00:00:00Z")
        transport = InjectedTransport(
            head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )
        with pytest.raises(stop_error) as exc:
            execute_transport_and_raw_freeze(
                sandbox,
                approval_record=approval,
                transport=transport,
                published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
                official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
            )
        assert_stop_state(exc.value, "PRE_DATA_DRIFT")
        assert transport.head_calls == []
        assert transport.get_calls == []
        _assert_no_records_created(sandbox.transport_record_path, sandbox.raw_record_path)


@pytest.mark.parametrize(
    ("case_id", "mutate_overlay"),
    (
        (
            "wrong-overlay-schema",
            lambda sandbox: _replace_once_in_file(
                sandbox.overlay_path,
                'schema: "raptor.eval.prospective_dataset_overlay.v1"',
                'schema: "raptor.eval.prospective_dataset_overlay.v9"',
            ),
        ),
        (
            "historical-labels-snapshot",
            lambda sandbox: _replace_once_in_file(
                sandbox.overlay_path,
                'effective_labels_snapshot: "clinvar_2026-08-monthly-amendment-v3"',
                'effective_labels_snapshot: "clinvar_2026-07-07"',
            ),
        ),
        (
            "wrong-base-config-path",
            lambda sandbox: _replace_once_in_file(
                sandbox.overlay_path,
                'base_config_path: "configs/eval/tsc2.yaml"',
                'base_config_path: "configs/eval/tsc2_other.yaml"',
            ),
        ),
        (
            "wrong-transport-freeze-record-path",
            lambda sandbox: _replace_once_in_file(
                sandbox.overlay_path,
                'transport_freeze_record: "data/census/tsc_prospective_validation_2026-08_amendment_v3_transport_freeze.json"',
                'transport_freeze_record: "data/census/rogue_transport_freeze.json"',
            ),
        ),
        (
            "wrong-raw-freeze-record-path",
            lambda sandbox: _replace_once_in_file(
                sandbox.overlay_path,
                'raw_freeze_record: "data/census/tsc_prospective_validation_2026-08_amendment_v3_raw_freeze.json"',
                'raw_freeze_record: "data/census/rogue_raw_freeze.json"',
            ),
        ),
    ),
)
def test_overlay_required_values_are_rejected_by_merge_and_executor_before_network(
    case_id: str,
    mutate_overlay: Callable[[Any], None],
) -> None:
    _require_freeze_contract_symbols()
    invalid_error = require_exception("ProspectiveInvalidStateError")
    with prospective_sandbox(f"overlay-required-values-{case_id}") as sandbox:
        mutate_overlay(sandbox)
        approval = build_approval_record(sandbox)

        with pytest.raises(invalid_error) as exc_merge:
            merge_overlay(sandbox)
        assert getattr(exc_merge.value, "code", None) == "INVALID"

        transport = InjectedTransport(
            head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )
        caught: BaseException | None = None
        result: dict[str, Any] | None = None
        try:
            result = execute_transport_and_raw_freeze(
                sandbox,
                approval_record=approval,
                transport=transport,
                published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
                official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
            )
        except BaseException as exc:  # noqa: BLE001
            caught = exc

        if caught is None:
            assert result is not None
            assert result["terminal_outcome"] == "INVALID"
            assert isinstance(result.get("reason_code"), str) and result["reason_code"]
        elif isinstance(caught, invalid_error):
            assert getattr(caught, "code", None) == "INVALID"
        else:
            raise caught

        assert transport.head_calls == []
        assert transport.get_calls == []
        _assert_no_records_created(sandbox.transport_record_path, sandbox.raw_record_path)


def test_executor_rejects_alternate_in_root_record_paths_and_only_allows_registered_paths() -> None:
    _require_freeze_contract_symbols()
    invalid_error = require_exception("ProspectiveInvalidStateError")
    with prospective_sandbox("alternate-in-root-record-paths") as sandbox:
        approval = build_approval_record(sandbox)
        alt_transport = sandbox.repo_root / "data" / "census" / "alternate_transport_freeze.json"
        alt_raw = sandbox.repo_root / "data" / "census" / "alternate_raw_freeze.json"
        transport = InjectedTransport(
            head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )
        caught: BaseException | None = None
        result: dict[str, Any] | None = None
        try:
            result = execute_transport_and_raw_freeze(
                sandbox,
                approval_record=approval,
                transport=transport,
                published_archive_date_lookup=_published_date_lookup_ok(sandbox.exact_url),
                official_md5_lookup=_official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes),
                transport_record_path=alt_transport,
                raw_record_path=alt_raw,
            )
        except BaseException as exc:  # noqa: BLE001
            caught = exc

        if caught is None:
            assert result is not None
            assert result["terminal_outcome"] == "INVALID"
            assert isinstance(result.get("reason_code"), str) and result["reason_code"]
        elif isinstance(caught, invalid_error):
            assert getattr(caught, "code", None) == "INVALID"
        else:
            raise caught

        assert transport.head_calls == []
        assert transport.get_calls == []
        assert not alt_transport.exists()
        assert not alt_raw.exists()
        assert not sandbox.transport_record_path.exists()
        assert not sandbox.raw_record_path.exists()


def test_historical_blocked_data_artifact_is_immutable() -> None:
    spec = yaml.safe_load(
        (REPO_ROOT / "docs" / "project" / "specs" / "clinvar-2026-08-prospective-amendment-v3.yaml").read_text(
            encoding="utf-8"
        )
    )
    if not isinstance(spec, dict):
        pytest.fail("spec must parse to a mapping")
    recorded = spec["historical_terminal_result"]
    rel = str(recorded["path"]).replace("\\", "/")
    git_dir, git_work_tree = prospective_red_helpers._resolve_git_metadata()
    resolved = subprocess.run(
        ["git", "--no-pager", "--git-dir", git_dir, "--work-tree", git_work_tree, "rev-parse", f"HEAD:{rel}"],
        cwd=git_work_tree,
        check=False,
        capture_output=True,
        text=True,
    )
    if resolved.returncode != 0:
        pytest.fail(f"unable to resolve historical artifact blob: {resolved.stderr or resolved.stdout}")
    assert resolved.stdout.strip() == recorded["git_blob_sha1"]
    assert canonical_lf_sha256_path(HISTORICAL_BLOCKED_PATH) == recorded["canonical_lf_sha256"]
