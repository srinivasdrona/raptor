"""Offline coverage for `raptor.eval.prospective_exact_source_metadata_lookups`
-- the hard-wired production `published_archive_date_lookup`/
`official_md5_lookup` ports (round 6: real implementations, no longer
permanent fail-closed stubs). Every test here is fully offline: fake
HTTPS connection/response fixtures only, never a real socket, and the
`_NoSocketModule`-style guard below fails loudly if anything ever tries
to use one. NO NCBI/ClinVar/archive network access of any kind."""
from __future__ import annotations

import hashlib
import http.client
import inspect
import ssl
from typing import Any
from urllib.parse import urlsplit

import pytest
import yaml

from tests.eval._clinvar_2026_08_prospective_red_helpers import REPO_ROOT

METADATA_MODULE = "raptor.eval.prospective_exact_source_metadata_lookups"


def _import_module() -> Any:
    import importlib

    try:
        return importlib.import_module(METADATA_MODULE)
    except ImportError as exc:
        pytest.fail(f"RED: missing planned metadata-lookups module {METADATA_MODULE}: {exc}", pytrace=False)


def _registered_pins() -> dict[str, str]:
    spec_path = REPO_ROOT / "docs" / "project" / "specs" / "clinvar-2026-08-prospective-amendment-v2.yaml"
    if not spec_path.is_file():
        pytest.fail(f"missing registration spec at {spec_path}")
    loaded = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    dataset_registration = loaded["dataset_registration"]
    registered_url = str(dataset_registration["exact_url"])
    pins = dataset_registration["metadata_source_pins"]
    parsed = urlsplit(str(pins["official_md5_url"]))
    if parsed.scheme != "https" or not parsed.hostname or not parsed.path:
        pytest.fail("metadata_source_pins.official_md5_url must be an https URL with host+path")
    return {
        "registered_url": registered_url,
        "published_archive_date": str(pins["published_archive_date"]),
        "published_archive_date_authority": str(pins["published_archive_date_authority"]),
        "official_md5_url": str(pins["official_md5_url"]),
        "official_md5_host": parsed.hostname,
        "official_md5_path": parsed.path,
        "official_md5_expected_filename": str(pins["official_md5_expected_filename"]),
    }


class _NoSocketModule:
    def socket(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("live sockets are forbidden in this test")

    def create_connection(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("live sockets are forbidden in this test")


class _FakeTLSContext:
    def __init__(self) -> None:
        self.check_hostname = True
        self.verify_mode = ssl.CERT_REQUIRED


class _InsecureTLSContext:
    def __init__(self) -> None:
        self.check_hostname = False
        self.verify_mode = ssl.CERT_NONE


class _FakeHTTPResponse:
    def __init__(self, *, status: int, headers: list[tuple[str, str]], body: bytes) -> None:
        self.status = status
        self.reason = "OK"
        self._headers = list(headers)
        self._body = body
        self.read_calls: list[int] = []

    def getheaders(self) -> list[tuple[str, str]]:
        return list(self._headers)

    def getheader(self, name: str, default: Any = None) -> Any:
        for key, value in self._headers:
            if key.lower() == name.lower():
                return value
        return default

    def read(self, amt: int = -1) -> bytes:
        self.read_calls.append(int(amt))
        if amt is None or amt < 0:
            return self._body
        return self._body[:amt]


class _FakeHTTPSConnection:
    def __init__(
        self, host: str, *, timeout: Any = None, context: Any = None, responses: list[_FakeHTTPResponse], **kwargs: Any
    ) -> None:
        self.host = host
        self.timeout = timeout
        self.context = context
        self.extra_kwargs = dict(kwargs)
        self._responses = list(responses)
        self.requests: list[dict[str, Any]] = []
        self.closed = False

    def request(self, method: str, path: str, body: Any = None, headers: Any = None, **kwargs: Any) -> None:
        self.requests.append({"method": method, "path": path, "body": body, "headers": headers})

    def getresponse(self) -> _FakeHTTPResponse:
        if not self._responses:
            raise AssertionError("no fake response queued")
        return self._responses.pop(0)

    def close(self) -> None:
        self.closed = True


def _assert_connection_security(conn: _FakeHTTPSConnection) -> None:
    assert conn.timeout is not None
    assert 0 < float(conn.timeout) <= 120
    assert conn.context is not None
    assert getattr(conn.context, "check_hostname", None) is True
    assert getattr(conn.context, "verify_mode", None) == ssl.CERT_REQUIRED
    for request in conn.requests:
        headers = request["headers"] or {}
        names = {str(key).lower() for key in headers.keys()} if hasattr(headers, "keys") else set()
        assert "authorization" not in names
        assert "proxy-authorization" not in names


def _connection_factory_for(
    responses: list[_FakeHTTPResponse], attempted_hosts: list[str], created: list[_FakeHTTPSConnection]
) -> Any:
    def _factory(host: str, *, timeout: Any = None, context: Any = None, **kwargs: Any) -> _FakeHTTPSConnection:
        attempted_hosts.append(host)
        conn = _FakeHTTPSConnection(host, timeout=timeout, context=context, responses=list(responses), **kwargs)
        created.append(conn)
        return conn

    return _factory


def _md5_hexdigest(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


# ---------------------------------------------------------------------------
# published_archive_date_lookup
# ---------------------------------------------------------------------------


def test_published_archive_date_lookup_returns_pinned_date_and_nonblank_authority() -> None:
    module = _import_module()
    pins = _registered_pins()
    result = module.published_archive_date_lookup(pins["registered_url"])
    assert isinstance(result, dict)
    assert result["published_archive_date"] == pins["published_archive_date"] == "2026-08-06"
    assert isinstance(result["source_identity"], str) and result["source_identity"].strip()
    assert result["source_identity"] == pins["published_archive_date_authority"]


def test_published_archive_date_lookup_rejects_unregistered_url_without_any_network() -> None:
    module = _import_module()
    pins = _registered_pins()
    with pytest.raises(module.MetadataLookupPolicyError) as exc_info:
        module.published_archive_date_lookup(pins["registered_url"] + ".evil")
    assert exc_info.value.reason_code == module.URL_POLICY_REASON


# ---------------------------------------------------------------------------
# official_md5_lookup
# ---------------------------------------------------------------------------


def test_official_md5_lookup_uses_real_stdlib_network_defaults() -> None:
    module = _import_module()
    signature = inspect.signature(module.official_md5_lookup)
    assert signature.parameters["connection_factory"].default is http.client.HTTPSConnection
    assert signature.parameters["tls_context_factory"].default is ssl.create_default_context


def test_official_md5_lookup_rejects_unregistered_url_before_any_connection() -> None:
    module = _import_module()
    pins = _registered_pins()
    attempted_hosts: list[str] = []
    created: list[_FakeHTTPSConnection] = []
    with pytest.raises(module.MetadataLookupPolicyError) as exc_info:
        module.official_md5_lookup(
            pins["registered_url"] + ".evil",
            connection_factory=_connection_factory_for([], attempted_hosts, created),
            tls_context_factory=_FakeTLSContext,
        )
    assert exc_info.value.reason_code == module.URL_POLICY_REASON
    assert attempted_hosts == []
    assert created == []


def test_official_md5_lookup_rejects_insecure_tls_context_before_any_connection() -> None:
    module = _import_module()
    pins = _registered_pins()
    attempted_hosts: list[str] = []
    created: list[_FakeHTTPSConnection] = []
    with pytest.raises(module.MetadataLookupConfigurationError):
        module.official_md5_lookup(
            pins["registered_url"],
            connection_factory=_connection_factory_for([], attempted_hosts, created),
            tls_context_factory=_InsecureTLSContext,
        )
    assert attempted_hosts == []
    assert created == []


def test_official_md5_lookup_successful_parse_bare_hex_no_filename() -> None:
    module = _import_module()
    pins = _registered_pins()
    digest = _md5_hexdigest(b"variant_summary_2026-08.txt.gz contents")
    response = _FakeHTTPResponse(status=200, headers=[("Content-Type", "text/plain")], body=f"{digest}\n".encode("ascii"))
    attempted_hosts: list[str] = []
    created: list[_FakeHTTPSConnection] = []
    result = module.official_md5_lookup(
        pins["registered_url"],
        connection_factory=_connection_factory_for([response], attempted_hosts, created),
        tls_context_factory=_FakeTLSContext,
    )
    assert result == {"official_md5": digest, "source_identity": pins["official_md5_url"]}
    assert attempted_hosts == [pins["official_md5_host"]]
    assert len(created) == 1
    request = created[0].requests[0]
    assert request["method"] == "GET"
    assert request["path"] == pins["official_md5_path"]
    _assert_connection_security(created[0])
    assert created[0].closed is True


def test_official_md5_lookup_successful_parse_with_matching_filename_md5sum_style() -> None:
    module = _import_module()
    pins = _registered_pins()
    digest = _md5_hexdigest(b"another payload")
    body = f"{digest}  {pins['official_md5_expected_filename']}\n".encode("ascii")
    response = _FakeHTTPResponse(status=200, headers=[], body=body)
    attempted_hosts: list[str] = []
    created: list[_FakeHTTPSConnection] = []
    result = module.official_md5_lookup(
        pins["registered_url"],
        connection_factory=_connection_factory_for([response], attempted_hosts, created),
        tls_context_factory=_FakeTLSContext,
    )
    assert result["official_md5"] == digest
    assert result["source_identity"] == pins["official_md5_url"]


def test_official_md5_lookup_successful_parse_uppercase_hex_is_lowercased() -> None:
    module = _import_module()
    pins = _registered_pins()
    digest = _md5_hexdigest(b"uppercase test payload")
    response = _FakeHTTPResponse(status=200, headers=[], body=digest.upper().encode("ascii"))
    attempted_hosts: list[str] = []
    created: list[_FakeHTTPSConnection] = []
    result = module.official_md5_lookup(
        pins["registered_url"],
        connection_factory=_connection_factory_for([response], attempted_hosts, created),
        tls_context_factory=_FakeTLSContext,
    )
    assert result["official_md5"] == digest


def test_official_md5_lookup_rejects_3xx_redirect_without_following() -> None:
    module = _import_module()
    pins = _registered_pins()
    for status in (301, 302, 303, 307, 308):
        response = _FakeHTTPResponse(
            status=status, headers=[("Location", "https://evil.example/redirected.md5")], body=b""
        )
        attempted_hosts: list[str] = []
        created: list[_FakeHTTPSConnection] = []
        with pytest.raises(module.MetadataLookupPolicyError) as exc_info:
            module.official_md5_lookup(
                pins["registered_url"],
                connection_factory=_connection_factory_for([response], attempted_hosts, created),
                tls_context_factory=_FakeTLSContext,
            )
        assert exc_info.value.reason_code == module.REDIRECT_POLICY_REASON
        assert attempted_hosts == [pins["official_md5_host"]]
        assert created[0].closed is True


def test_official_md5_lookup_rejects_non_200_non_redirect_status() -> None:
    module = _import_module()
    pins = _registered_pins()
    response = _FakeHTTPResponse(status=404, headers=[], body=b"not found")
    attempted_hosts: list[str] = []
    created: list[_FakeHTTPSConnection] = []
    with pytest.raises(module.MetadataLookupPolicyError) as exc_info:
        module.official_md5_lookup(
            pins["registered_url"],
            connection_factory=_connection_factory_for([response], attempted_hosts, created),
            tls_context_factory=_FakeTLSContext,
        )
    assert exc_info.value.reason_code == module.STATUS_POLICY_REASON


def test_official_md5_lookup_rejects_oversized_response_via_bounded_single_read() -> None:
    module = _import_module()
    pins = _registered_pins()
    oversized_body = (b"a" * 5000) + b"\n"
    response = _FakeHTTPResponse(status=200, headers=[], body=oversized_body)
    attempted_hosts: list[str] = []
    created: list[_FakeHTTPSConnection] = []
    with pytest.raises(module.MetadataLookupPolicyError) as exc_info:
        module.official_md5_lookup(
            pins["registered_url"],
            connection_factory=_connection_factory_for([response], attempted_hosts, created),
            tls_context_factory=_FakeTLSContext,
        )
    assert exc_info.value.reason_code == module.SIZE_POLICY_REASON
    # Exactly one bounded read call was made -- never an unbounded read.
    assert response.read_calls == [4097]


def test_official_md5_lookup_rejects_malformed_body() -> None:
    module = _import_module()
    pins = _registered_pins()
    response = _FakeHTTPResponse(status=200, headers=[], body=b"not-a-checksum-at-all")
    attempted_hosts: list[str] = []
    created: list[_FakeHTTPSConnection] = []
    with pytest.raises(module.MetadataLookupPolicyError) as exc_info:
        module.official_md5_lookup(
            pins["registered_url"],
            connection_factory=_connection_factory_for([response], attempted_hosts, created),
            tls_context_factory=_FakeTLSContext,
        )
    assert exc_info.value.reason_code == module.PARSE_POLICY_REASON


def test_official_md5_lookup_rejects_mismatched_filename() -> None:
    module = _import_module()
    pins = _registered_pins()
    digest = _md5_hexdigest(b"mismatched filename payload")
    body = f"{digest}  variant_summary_2099-01.txt.gz\n".encode("ascii")
    response = _FakeHTTPResponse(status=200, headers=[], body=body)
    attempted_hosts: list[str] = []
    created: list[_FakeHTTPSConnection] = []
    with pytest.raises(module.MetadataLookupPolicyError) as exc_info:
        module.official_md5_lookup(
            pins["registered_url"],
            connection_factory=_connection_factory_for([response], attempted_hosts, created),
            tls_context_factory=_FakeTLSContext,
        )
    assert exc_info.value.reason_code == module.FILENAME_POLICY_REASON
