from __future__ import annotations

import importlib
import inspect
import ssl
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
import yaml

from raptor.eval.prospective_freeze import MAX_DOWNLOAD_CHUNK_BYTES
from tests.eval._clinvar_2026_08_prospective_red_helpers import REPO_ROOT

TRANSPORT_MODULE = "raptor.eval.prospective_exact_source_transport"
TRANSPORT_FACTORY_NAME = "build_transport"
_ABSOLUTE_CHUNK_CAP_BYTES = 8 * 1024 * 1024
_URL_POLICY_REASON = "EXACT_REGISTERED_URL_REQUIRED"
_REDIRECT_POLICY_REASON = "REDIRECT_NOT_ALLOWED"


def _registration_contract() -> dict[str, str]:
    spec_path = REPO_ROOT / "docs" / "project" / "specs" / "clinvar-2026-08-prospective-amendment-v3.yaml"
    if not spec_path.is_file():
        pytest.fail(f"missing registration spec at {spec_path}")
    loaded = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        pytest.fail("registration spec must parse to a mapping")

    required_values = loaded["prospective_eval_overlay_lifecycle"]["required_values"]
    dataset_registration = loaded["dataset_registration"]
    registered_url = str(required_values["exact_archive_url"])
    if registered_url != str(dataset_registration["exact_url"]):
        pytest.fail("required_values.exact_archive_url must equal dataset_registration.exact_url")

    parsed = urlsplit(registered_url)
    if parsed.scheme != "https":
        pytest.fail("registered URL must use https")
    if not parsed.hostname or not parsed.path:
        pytest.fail("registered URL must include hostname and path")

    return {
        "registered_url": registered_url,
        "required_final_url": str(dataset_registration["required_final_url"]),
        "registered_host": parsed.hostname,
        "registered_path": parsed.path,
        "superseded_url": str(loaded["historical_terminal_result"]["original_registered_url"]),
    }


def _require_transport_factory() -> tuple[Any, Any]:
    try:
        module = importlib.import_module(TRANSPORT_MODULE)
    except ImportError as exc:
        pytest.fail(
            f"RED: missing planned exact-source transport module {TRANSPORT_MODULE}: {exc}",
            pytrace=False,
        )
    factory = getattr(module, TRANSPORT_FACTORY_NAME, None)
    if not callable(factory):
        pytest.fail(
            f"RED: missing planned transport factory {TRANSPORT_MODULE}.{TRANSPORT_FACTORY_NAME}",
            pytrace=False,
        )
    return module, factory


class _NoSocketModule:
    def socket(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("live sockets are forbidden in this test")

    def create_connection(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("live sockets are forbidden in this test")


class _FakeTLSContext:
    def __init__(self) -> None:
        self.check_hostname = True
        self.verify_mode = ssl.CERT_REQUIRED


class _FakeHTTPResponse:
    def __init__(self, *, status: int, headers: list[tuple[str, str]], body: bytes) -> None:
        self.status = status
        self.reason = "OK"
        self._headers = list(headers)
        self._body = body
        self._offset = 0
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
        if self._offset >= len(self._body):
            return b""
        if amt is None or amt < 0:
            start = self._offset
            self._offset = len(self._body)
            return self._body[start:]
        start = self._offset
        stop = min(len(self._body), start + amt)
        self._offset = stop
        return self._body[start:stop]


class _FakeHTTPSConnection:
    def __init__(self, host: str, *, timeout: Any, context: Any, responses: list[_FakeHTTPResponse], **kwargs: Any) -> None:
        self.host = host
        self.timeout = timeout
        self.context = context
        self.extra_kwargs = dict(kwargs)
        self._responses = list(responses)
        self.requests: list[dict[str, Any]] = []
        self.closed = False

    def request(self, method: str, path: str, body: Any = None, headers: Any = None, **kwargs: Any) -> None:
        self.requests.append(
            {
                "method": method,
                "path": path,
                "body": body,
                "headers": headers,
                "kwargs": dict(kwargs),
            }
        )

    def getresponse(self) -> _FakeHTTPResponse:
        if not self._responses:
            raise AssertionError("no fake response queued")
        return self._responses.pop(0)

    def close(self) -> None:
        self.closed = True


def _build_transport(
    factory: Any,
    *,
    connection_factory: Any,
    socket_module: Any,
    tls_context_factory: Any,
) -> Any:
    signature = inspect.signature(factory)
    if "connection_factory" not in signature.parameters:
        pytest.fail("transport factory must accept a connection_factory injection hook", pytrace=False)

    kwargs: dict[str, Any] = {"connection_factory": connection_factory}
    if "socket_module" in signature.parameters:
        kwargs["socket_module"] = socket_module
    if "tls_context_factory" in signature.parameters:
        kwargs["tls_context_factory"] = tls_context_factory
    if "head_timeout_seconds" in signature.parameters:
        kwargs["head_timeout_seconds"] = 15
    if "get_timeout_seconds" in signature.parameters:
        kwargs["get_timeout_seconds"] = 30
    if "max_chunk_bytes" in signature.parameters:
        kwargs["max_chunk_bytes"] = MAX_DOWNLOAD_CHUNK_BYTES

    try:
        transport = factory(**kwargs)
    except TypeError as exc:
        pytest.fail(f"transport factory invocation failed with offline hooks: {exc}", pytrace=False)

    if not callable(getattr(transport, "head", None)):
        pytest.fail("transport object must provide head(url)", pytrace=False)
    if not callable(getattr(transport, "stream_get", None)):
        pytest.fail("transport object must provide stream_get(url, chunk_bytes)", pytrace=False)
    return transport


def _header_names(headers: Any) -> set[str]:
    if headers is None:
        return set()
    if isinstance(headers, Mapping):
        return {str(key).lower() for key in headers.keys()}
    if isinstance(headers, list):
        names: set[str] = set()
        for entry in headers:
            if isinstance(entry, (list, tuple)) and len(entry) == 2:
                names.add(str(entry[0]).lower())
        return names
    return set()


def _assert_transport_rejection(exc: BaseException, *, expected_reason: str) -> None:
    assert type(exc).__name__ in {
        "ProspectiveInvalidStateError",
        "ProspectiveContractError",
        "ExactSourceTransportError",
        "ExactSourceTransportPolicyError",
        "TransportPolicyError",
    }
    observed_reason = getattr(exc, "reason_code", None)
    reason_text = getattr(exc, "reason", None)
    if not isinstance(reason_text, str) or not reason_text.strip():
        reason_text = str(exc)
    if observed_reason is not None:
        assert observed_reason == expected_reason
    else:
        assert expected_reason.lower() in reason_text.lower()


def _assert_connection_security(conn: _FakeHTTPSConnection) -> None:
    assert conn.timeout is not None
    assert 0 < float(conn.timeout) <= 120
    assert conn.context is not None
    assert getattr(conn.context, "check_hostname", None) is True
    assert getattr(conn.context, "verify_mode", None) == ssl.CERT_REQUIRED
    for request in conn.requests:
        header_names = _header_names(request["headers"])
        assert "authorization" not in header_names
        assert "proxy-authorization" not in header_names


def _negative_urls(contract: Mapping[str, str]) -> list[tuple[str, str]]:
    registered_url = contract["registered_url"]
    host = contract["registered_host"]
    path = contract["registered_path"]
    if not host or not path:
        pytest.fail("registered URL contract must include host and path")
    return [
        ("old-adr-0013-path", contract["superseded_url"]),
        ("userinfo-host-confusion", f"https://{host}@evil.example{path}"),
        ("uppercase-host", f"https://{host.upper()}{path}"),
        ("explicit-port-default-443", f"https://{host}:443{path}"),
        ("trailing-slash", f"{registered_url}/"),
        ("percent-encoded-path", f"https://{host}{path.replace('.txt.gz', '.txt%2Egz')}"),
        ("query-string", f"{registered_url}?download=1"),
        ("fragment", f"{registered_url}#raw"),
    ]


def test_exact_source_transport_factory_exposes_offline_injection_hooks() -> None:
    _module, factory = _require_transport_factory()
    _build_transport(
        factory,
        connection_factory=lambda *_args, **_kwargs: pytest.fail("connection hook invoked unexpectedly"),
        socket_module=_NoSocketModule(),
        tls_context_factory=_FakeTLSContext,
    )


def test_exact_source_transport_rejects_unregistered_urls_before_any_connection() -> None:
    contract = _registration_contract()
    _module, factory = _require_transport_factory()
    attempted_hosts: list[str] = []
    created_connections: list[_FakeHTTPSConnection] = []

    def _connection_factory(host: str, *, timeout: Any = None, context: Any = None, **kwargs: Any) -> _FakeHTTPSConnection:
        attempted_hosts.append(host)
        conn = _FakeHTTPSConnection(host, timeout=timeout, context=context, responses=[], **kwargs)
        created_connections.append(conn)
        return conn

    transport = _build_transport(
        factory,
        connection_factory=_connection_factory,
        socket_module=_NoSocketModule(),
        tls_context_factory=_FakeTLSContext,
    )
    for _case_id, bad_url in _negative_urls(contract):
        with pytest.raises(Exception) as head_exc:  # noqa: BLE001
            transport.head(bad_url)
        _assert_transport_rejection(head_exc.value, expected_reason=_URL_POLICY_REASON)
        with pytest.raises(Exception) as get_exc:  # noqa: BLE001
            list(transport.stream_get(bad_url, chunk_bytes=4096))
        _assert_transport_rejection(get_exc.value, expected_reason=_URL_POLICY_REASON)

    assert attempted_hosts == []
    assert created_connections == []


def test_exact_source_transport_head_success_surfaces_duplicate_raw_headers_and_status() -> None:
    contract = _registration_contract()
    _module, factory = _require_transport_factory()
    duplicate_headers = [
        ("Last-Modified", "Thu, 06 Aug 2026 04:05:02 GMT"),
        ("Last-Modified", "Thu, 06 Aug 2026 04:05:02 GMT"),
        ("Content-Length", "441792560"),
    ]
    head_response = _FakeHTTPResponse(status=200, headers=duplicate_headers, body=b"")
    attempted_hosts: list[str] = []
    created_connections: list[_FakeHTTPSConnection] = []

    def _connection_factory(host: str, *, timeout: Any = None, context: Any = None, **kwargs: Any) -> _FakeHTTPSConnection:
        attempted_hosts.append(host)
        conn = _FakeHTTPSConnection(host, timeout=timeout, context=context, responses=[head_response], **kwargs)
        created_connections.append(conn)
        return conn

    transport = _build_transport(
        factory,
        connection_factory=_connection_factory,
        socket_module=_NoSocketModule(),
        tls_context_factory=_FakeTLSContext,
    )
    payload = transport.head(contract["registered_url"])
    assert isinstance(payload, dict)
    assert payload["status_code"] == 200
    assert payload["final_url"] == contract["required_final_url"]
    assert payload["raw_headers"] == duplicate_headers
    assert attempted_hosts == [contract["registered_host"]]
    assert len(created_connections) == 1
    assert len(created_connections[0].requests) == 1
    request = created_connections[0].requests[0]
    assert request["method"] == "HEAD"
    assert request["path"] == contract["registered_path"]
    _assert_connection_security(created_connections[0])


def test_exact_source_transport_head_404_and_3xx_return_structured_payload_without_follow() -> None:
    contract = _registration_contract()
    _module, factory = _require_transport_factory()
    redirect_location = contract["superseded_url"]
    cases = [
        (404, [("Content-Type", "text/plain")], None),
        (302, [("Location", redirect_location), ("Content-Type", "text/plain")], redirect_location),
    ]
    for status_code, headers, location in cases:
        response = _FakeHTTPResponse(status=status_code, headers=headers, body=b"")
        attempted_hosts: list[str] = []
        created_connections: list[_FakeHTTPSConnection] = []

        def _connection_factory(host: str, *, timeout: Any = None, context: Any = None, **kwargs: Any) -> _FakeHTTPSConnection:
            attempted_hosts.append(host)
            conn = _FakeHTTPSConnection(host, timeout=timeout, context=context, responses=[response], **kwargs)
            created_connections.append(conn)
            return conn

        transport = _build_transport(
            factory,
            connection_factory=_connection_factory,
            socket_module=_NoSocketModule(),
            tls_context_factory=_FakeTLSContext,
        )
        payload = transport.head(contract["registered_url"])
        assert isinstance(payload, dict)
        assert payload["status_code"] == status_code
        assert payload["raw_headers"] == headers
        assert isinstance(payload["final_url"], str) and payload["final_url"]
        if location is None:
            assert payload["final_url"] == contract["required_final_url"]
        else:
            assert payload["final_url"] != contract["registered_url"]
            assert payload["final_url"] == location or payload["final_url"].startswith("REDIRECT_REJECTED:")
        assert attempted_hosts == [contract["registered_host"]]
        assert len(created_connections) == 1
        assert len(created_connections[0].requests) == 1
        request = created_connections[0].requests[0]
        assert request["method"] == "HEAD"
        assert request["path"] == contract["registered_path"]
        _assert_connection_security(created_connections[0])


def test_exact_source_transport_redirect_get_rejected_without_off_host_or_off_path_follow() -> None:
    contract = _registration_contract()
    _module, factory = _require_transport_factory()
    redirects = [
        ("off-host-redirect", f"https://example.org{contract['registered_path']}"),
        ("off-path-redirect", contract["superseded_url"]),
    ]
    for _case_id, redirect_target in redirects:
        attempted_hosts: list[str] = []
        redirect_response = _FakeHTTPResponse(status=302, headers=[("Location", redirect_target)], body=b"")
        created_connections: list[_FakeHTTPSConnection] = []

        def _connection_factory(host: str, *, timeout: Any = None, context: Any = None, **kwargs: Any) -> _FakeHTTPSConnection:
            attempted_hosts.append(host)
            conn = _FakeHTTPSConnection(host, timeout=timeout, context=context, responses=[redirect_response], **kwargs)
            created_connections.append(conn)
            return conn

        transport = _build_transport(
            factory,
            connection_factory=_connection_factory,
            socket_module=_NoSocketModule(),
            tls_context_factory=_FakeTLSContext,
        )
        with pytest.raises(Exception) as exc_info:  # noqa: BLE001
            list(transport.stream_get(contract["registered_url"], chunk_bytes=4096))
        _assert_transport_rejection(exc_info.value, expected_reason=_REDIRECT_POLICY_REASON)
        assert attempted_hosts == [contract["registered_host"]]
        assert len(created_connections) == 1
        assert len(created_connections[0].requests) == 1
        request = created_connections[0].requests[0]
        assert request["method"] == "GET"
        assert request["path"] == contract["registered_path"]
        _assert_connection_security(created_connections[0])


def test_exact_source_transport_bounded_streaming_caps_response_read_amount_and_chunk_size() -> None:
    contract = _registration_contract()
    _module, factory = _require_transport_factory()
    requested_chunk_bytes = max(MAX_DOWNLOAD_CHUNK_BYTES * 16, _ABSOLUTE_CHUNK_CAP_BYTES + 123)
    effective_cap = min(requested_chunk_bytes, _ABSOLUTE_CHUNK_CAP_BYTES, MAX_DOWNLOAD_CHUNK_BYTES)
    body = b"x" * (MAX_DOWNLOAD_CHUNK_BYTES * 3 + 777)
    assert len(body) > MAX_DOWNLOAD_CHUNK_BYTES
    stream_response = _FakeHTTPResponse(status=200, headers=[("Content-Length", str(len(body)))], body=body)
    created_connections: list[_FakeHTTPSConnection] = []
    attempted_hosts: list[str] = []

    def _connection_factory(host: str, *, timeout: Any = None, context: Any = None, **kwargs: Any) -> _FakeHTTPSConnection:
        attempted_hosts.append(host)
        conn = _FakeHTTPSConnection(host, timeout=timeout, context=context, responses=[stream_response], **kwargs)
        created_connections.append(conn)
        return conn

    transport = _build_transport(
        factory,
        connection_factory=_connection_factory,
        socket_module=_NoSocketModule(),
        tls_context_factory=_FakeTLSContext,
    )
    chunks = list(transport.stream_get(contract["registered_url"], chunk_bytes=requested_chunk_bytes))
    assert chunks
    assert b"".join(chunks) == body
    assert attempted_hosts == [contract["registered_host"]]
    assert len(created_connections) == 1
    assert len(created_connections[0].requests) == 1
    request = created_connections[0].requests[0]
    assert request["method"] == "GET"
    assert request["path"] == contract["registered_path"]
    assert stream_response.read_calls
    assert -1 not in stream_response.read_calls
    assert all(amt > 0 for amt in stream_response.read_calls)
    assert all(amt <= effective_cap for amt in stream_response.read_calls)
    assert max(len(chunk) for chunk in chunks) <= effective_cap
    _assert_connection_security(created_connections[0])
