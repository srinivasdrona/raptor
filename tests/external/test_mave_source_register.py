from __future__ import annotations

import hashlib
import socket
from importlib import import_module
from pathlib import Path

import pytest


def _register_api() -> dict[str, object]:
    try:
        module = import_module("raptor.external.mave.register")
    except ImportError as exc:
        pytest.fail(f"external MAVE register is not implemented: {exc}")
    return {
        "SourceRegisterEntry": module.SourceRegisterEntry,
        "SourceVerificationError": module.SourceVerificationError,
        "ConfirmationPendingError": module.ConfirmationPendingError,
        "verify_registered_source": module.verify_registered_source,
    }


def _source_api() -> dict[str, object]:
    try:
        module = import_module("raptor.external.mave.source")
    except ImportError as exc:
        pytest.fail(f"external MAVE source loader is not implemented: {exc}")
    return {
        "MaveScoreRecord": module.MaveScoreRecord,
        "ScoreContractError": module.ScoreContractError,
        "load_score_records": module.load_score_records,
    }


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _make_entry(payload_sha256: str, *, verification: str = "verified"):
    api = _register_api()
    return api["SourceRegisterEntry"](
        urn="urn:mavedb:00001201-a-1",
        gene="TSC2",
        transcript="NM_000548.5",
        license="CC0-1.0",
        sha256=payload_sha256,
        variant_count=208,
        verification=verification,
    )


def test_register_verifies_public_cc0_transcript_and_hash_fail_closed() -> None:
    api = _register_api()
    entry = _make_entry("a" * 64)

    api["verify_registered_source"](
        entry,
        observed_transcript="NM_000548.5",
        observed_license="CC0-1.0",
        observed_sha256="a" * 64,
        observed_variant_count=208,
    )

    with pytest.raises(api["SourceVerificationError"], match="transcript"):
        api["verify_registered_source"](
            entry,
            observed_transcript="NM_999999.1",
            observed_license="CC0-1.0",
            observed_sha256="a" * 64,
            observed_variant_count=208,
        )

    with pytest.raises(api["SourceVerificationError"], match="sha|hash"):
        api["verify_registered_source"](
            entry,
            observed_transcript="NM_000548.5",
            observed_license="CC0-1.0",
            observed_sha256="b" * 64,
            observed_variant_count=208,
        )

    with pytest.raises(api["ConfirmationPendingError"]):
        api["verify_registered_source"](
            _make_entry("a" * 64, verification="confirm_pending"),
            observed_transcript="NM_000548.5",
            observed_license="CC0-1.0",
            observed_sha256="a" * 64,
            observed_variant_count=208,
        )

    with pytest.raises(api["SourceVerificationError"], match="pinned|unpinned|sha"):
        api["verify_registered_source"](
            _make_entry(""),
            observed_transcript="NM_000548.5",
            observed_license="CC0-1.0",
            observed_sha256="a" * 64,
            observed_variant_count=208,
        )


def test_score_contract_requires_variant_hgvs_and_numeric_score_columns(tmp_path: Path) -> None:
    api = _source_api()
    payload = "variant_id\thgvs_c\nNC_000016.10:100:A:G\tc.100A>G\n"
    path = tmp_path / "bad_scores.tsv"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(api["ScoreContractError"], match="score"):
        api["load_score_records"](path, _make_entry(_sha256(payload)))


def test_loader_supports_local_fixture_and_injected_fetcher_without_real_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _source_api()
    payload = (
        "variant_id\thgvs_c\tscore\treference\n"
        "NC_000016.10:100:A:G\tc.100A>G\t0.200\tA\n"
        "NC_000016.10:200:C:T\tc.200C>T\t0.600\tC\n"
    )
    entry = _make_entry(_sha256(payload))

    def _no_network(*args, **kwargs):
        raise AssertionError("real network is forbidden in unit tests")

    monkeypatch.setattr(socket, "create_connection", _no_network)

    local_path = tmp_path / "mave.tsv"
    local_path.write_text(payload, encoding="utf-8")
    local_rows = api["load_score_records"](local_path, entry)
    assert [row.variant_id for row in local_rows] == [
        "NC_000016.10:100:A:G",
        "NC_000016.10:200:C:T",
    ]

    seen_urls: list[str] = []

    def fake_fetcher(url: str) -> str:
        seen_urls.append(url)
        return payload

    remote_rows = api["load_score_records"](
        "https://example.invalid/mavedb/00001201-a-1.tsv",
        entry,
        fetcher=fake_fetcher,
    )
    assert seen_urls == ["https://example.invalid/mavedb/00001201-a-1.tsv"]
    assert [row.variant_id for row in remote_rows] == [
        "NC_000016.10:100:A:G",
        "NC_000016.10:200:C:T",
    ]
