from __future__ import annotations

import uuid
from typing import Any

import pytest

from tests.eval._clinvar_2026_08_prospective_red_helpers import (
    InjectedLookup,
    InjectedTransport,
    build_approval_record,
    execute_transport_and_raw_freeze,
    make_head_payload,
    prospective_sandbox,
    require_module,
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
                "source_identity": "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/archive/",
                "unavailable_reason": "NCBI publishes no checksum for monthly tab-delimited archive copies.",
                "verification_mode": "EXACT_URL_HEAD_CONTINUITY_PLUS_LOCAL_SHA256_MD5",
            }
        }
    )


def test_external_root_need_not_be_globally_empty() -> None:
    with prospective_sandbox("external-root-non-empty") as sandbox:
        legacy_dir = sandbox.external_root / "legacy-run-001"
        legacy_dir.mkdir(parents=True, exist_ok=False)
        legacy_note = legacy_dir / "README.txt"
        legacy_note.write_text("legacy-bytes", encoding="utf-8")

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
        assert legacy_note.read_text(encoding="utf-8") == "legacy-bytes"


def test_run_scope_destination_must_be_fresh_and_never_overwrite_existing_archive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = require_module()
    with prospective_sandbox("external-root-run-scope-collision") as sandbox:
        approval = build_approval_record(sandbox)
        forced_scope_hex = "a" * 32
        existing_dir = sandbox.external_root / forced_scope_hex
        existing_dir.mkdir(parents=True, exist_ok=False)
        archive_name = str(sandbox.spec["dataset_registration"]["filename"])
        existing_archive = existing_dir / archive_name
        existing_archive_bytes = b"already-present-archive-bytes"
        existing_archive.write_bytes(existing_archive_bytes)

        real_uuid4 = module.uuid.uuid4
        planned = [uuid.UUID(forced_scope_hex), uuid.UUID("b" * 32)]

        def _fixed_uuid4() -> uuid.UUID:
            if planned:
                return planned.pop(0)
            return real_uuid4()

        monkeypatch.setattr(module.uuid, "uuid4", _fixed_uuid4)

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
        assert existing_archive.read_bytes() == existing_archive_bytes
        assert not sandbox.raw_record_path.exists()
