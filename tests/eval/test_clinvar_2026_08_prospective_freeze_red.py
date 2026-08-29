from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

from tests.eval._clinvar_2026_08_prospective_red_helpers import (
    HISTORICAL_BLOCKED_PATH,
    REPO_ROOT,
    InjectedLookup,
    InjectedTransport,
    assert_record_content_hash,
    assert_stop_state,
    build_approval_record,
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
    validate_pre_data_approval,
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


def _official_md5_lookup_ok(url: str, archive_bytes: bytes) -> InjectedLookup:
    return InjectedLookup(
        {
            url: {
                "official_md5": md5_hex(archive_bytes),
                "source_identity": "ncbi-official-md5-manifest-2026-08",
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


def _mutate_approval(
    approval: dict[str, Any],
    *,
    decision: str | None = None,
    approver: str | None = None,
    approved_at: str | None = None,
    immutable_inputs_verified: bool | None = None,
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
    if immutable_inputs_verified is not None:
        mutated["immutable_inputs_verified"] = immutable_inputs_verified
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
            runtime_identity=approval["x64_freeze"],
            label_reader=_forbidden("label_reader"),
            benchmark_builder=_forbidden("benchmark_builder"),
            scoring_runner=_forbidden("scoring_runner"),
        )

        assert result["stage_status"] == "TRANSPORT_AND_RAW_FROZEN"
        assert result.get("terminal_outcome") is None
        assert result["transport_metadata_not_content_identity"] is True
        assert result["runtime_identity"] == approval["x64_freeze"]
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
        ("immutable-inputs-false", lambda approval: _mutate_approval(approval, immutable_inputs_verified=False), None, "PRE_DATA_IMPLEMENTATION_NOT_READY"),
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
    ),
)
def test_runtime_identity_drift_is_pre_data_drift_with_zero_network(field_name: str, drifted_value: str) -> None:
    _require_freeze_contract_symbols()
    stop_error = require_exception("ProspectiveStopStateError")
    with prospective_sandbox(f"runtime-drift-{field_name}") as sandbox:
        approval = build_approval_record(sandbox)
        runtime_identity = dict(approval["x64_freeze"])
        runtime_identity[field_name] = drifted_value
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
                runtime_identity=runtime_identity,
            )
        assert_stop_state(exc.value, "PRE_DATA_DRIFT")
        assert transport.head_calls == []
        assert transport.get_calls == []
        _assert_no_records_created(sandbox.transport_record_path, sandbox.raw_record_path)


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
        ("official-md5-source-missing", 200, None, "ok", "source-missing", "OFFICIAL_MD5_SOURCE_MISSING", 0),
        ("official-md5-mismatch", 200, None, "ok", "mismatch", "OFFICIAL_MD5_MISMATCH", 1),
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
            md5_lookup = InjectedLookup({sandbox.exact_url: {"official_md5": md5_hex(sandbox.archive_bytes), "source_identity": ""}})
        elif md5_payload == "mismatch":
            md5_lookup = InjectedLookup(
                {
                    sandbox.exact_url: {
                        "official_md5": "0" * 32,
                        "source_identity": "ncbi-official-md5-manifest-2026-08",
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
            if not hasattr(os, "mkfifo"):
                pytest.skip("fifo creation unsupported")
            os.mkfifo(destination)
        elif destination_case == "special-socket-file":
            if not hasattr(socket, "AF_UNIX"):
                pytest.skip("unix sockets unsupported")
            unix_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                unix_socket.bind(str(destination))
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
        raw_payload["official_md5"] = "0" * 32
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
        assert blocked["terminal_outcome"] == "BLOCKED_DATA"

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
        shared_transport = InjectedTransport(
            head_by_url={sandbox.exact_url: make_head_payload(sandbox)},
            body_by_url={sandbox.exact_url: sandbox.archive_bytes},
        )
        shared_date_lookup = _published_date_lookup_ok(sandbox.exact_url)
        shared_md5_lookup = _official_md5_lookup_ok(sandbox.exact_url, sandbox.archive_bytes)
        results: list[dict[str, Any]] = []
        errors: list[BaseException] = []
        lock = threading.Lock()

        def _worker() -> None:
            try:
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

        t1 = threading.Thread(target=_worker, daemon=True)
        t2 = threading.Thread(target=_worker, daemon=True)
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        assert len(results) + len(errors) == 2
        assert len(results) >= 1
        assert len(shared_transport.get_calls) == 1
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
            if "transport_record_content_hash" in item:
                assert item["transport_record_content_hash"] == transport_record["content_hash"]
            if "raw_record_content_hash" in item:
                assert item["raw_record_content_hash"] == raw_record["content_hash"]


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


def test_historical_blocked_data_artifact_is_immutable() -> None:
    spec = yaml.safe_load(
        (REPO_ROOT / "docs" / "project" / "specs" / "clinvar-2026-08-prospective-amendment-v2.yaml").read_text(
            encoding="utf-8"
        )
    )
    if not isinstance(spec, dict):
        pytest.fail("spec must parse to a mapping")
    recorded = spec["historical_terminal_result"]
    rel = str(recorded["path"]).replace("\\", "/")
    resolved = subprocess.run(
        ["git", "rev-parse", f"HEAD:{rel}"],
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    if resolved.returncode != 0:
        pytest.fail(f"unable to resolve historical artifact blob: {resolved.stderr or resolved.stdout}")
    assert resolved.stdout.strip() == recorded["git_blob_sha1"]
    assert canonical_lf_sha256_path(HISTORICAL_BLOCKED_PATH) == recorded["canonical_lf_sha256"]
