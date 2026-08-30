"""raptor.eval.prospective_exact_source_transport -- the ADR-0020 /
`docs/project/specs/clinvar-2026-08-prospective-amendment-v2.yaml`
EXACT-single-source HTTPS transport for `raptor.eval.prospective_freeze
.execute_transport_and_raw_freeze`'s injected `transport` port.

This module is deliberately bound to ONE registration's ONE registered
archive URL (`dataset_registration.exact_url` in the registration spec,
read fresh -- never cached -- on every call): every `head()`/`stream_get()`
call is rejected, before any connection is opened, unless its `url`
argument is an EXACT (byte-for-byte) match for that pinned URL. There is
no normalization, no case-folding, no default-port collapsing and no
query/fragment stripping before that comparison -- a URL that differs from
the registration in ANY way (host case, an explicit default port, a
trailing slash, percent-encoding, a query string, a fragment, or the
historical ADR-0013 URL) is rejected exactly like a completely different
host would be.

Every network primitive is caller-injectable (`connection_factory`,
`tls_context_factory`, `socket_module`) so tests can exercise the full
policy surface completely offline; the module-level defaults
(`http.client.HTTPSConnection`, `ssl.create_default_context`) are the ONLY
real network path this module ever provides, and TLS verification
(`check_hostname`/`CERT_REQUIRED`) is always on by construction. Neither
`head()` nor `stream_get()` ever follows a redirect: `head()` reports a
3xx/4xx status structurally (with the raw, duplicate-preserving response
headers and the true `Location`-derived `final_url`) instead of chasing
it, and `stream_get()` raises before reading a single byte of an
off-host, off-path, or even same-host/same-path 3xx response body. No
request ever carries an `Authorization`/`Proxy-Authorization` header, and
no proxy is ever consulted (this module never reads `HTTP_PROXY`/
`HTTPS_PROXY`, and `http.client.HTTPSConnection` performs no proxying on
its own). Every streamed read is clamped to the smaller of the caller's
requested chunk size, this transport's own configured ceiling, and an
absolute 8 MiB hard ceiling -- the archive is never read in one unbounded
`read()` call.
"""
from __future__ import annotations

import http.client
import ssl
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import urlsplit

import yaml

from raptor.eval.prospective_freeze import MAX_DOWNLOAD_CHUNK_BYTES

__all__ = [
    "ExactSourceTransportError",
    "ExactSourceTransportPolicyError",
    "build_transport",
]

#: This file's fixed location is `<repo>/src/raptor/eval/
#: prospective_exact_source_transport.py`, so the repo root is always this
#: file's great-grandparent (mirrors `raptor.census.cli.REPO_ROOT`).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_REGISTRATION_SPEC_PATH = (
    _REPO_ROOT / "docs" / "project" / "specs" / "clinvar-2026-08-prospective-amendment-v2.yaml"
)

#: Closed transport-policy reason-code vocabulary.
URL_POLICY_REASON = "EXACT_REGISTERED_URL_REQUIRED"
REDIRECT_POLICY_REASON = "REDIRECT_NOT_ALLOWED"

#: Absolute hard ceiling on any single streamed read -- independent of, and
#: always at least as strict as, the caller's/module's own chunk-size
#: request (`min(chunk_bytes, max_chunk_bytes, _ABSOLUTE_MAX_CHUNK_BYTES)`).
_ABSOLUTE_MAX_CHUNK_BYTES = 8 * 1024 * 1024

_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})

_MIN_TIMEOUT_SECONDS = 0
_MAX_TIMEOUT_SECONDS = 120


class ExactSourceTransportError(Exception):
    """Base class for every typed `prospective_exact_source_transport`
    failure (configuration/spec-loading failures that are never a policy
    rejection)."""


class ExactSourceTransportPolicyError(ExactSourceTransportError):
    """A closed transport-policy rejection -- an unregistered/mismatched
    URL (`URL_POLICY_REASON`) or a disallowed redirect
    (`REDIRECT_POLICY_REASON`). `.reason_code` is always one of the closed
    reason codes above; `.reason` is always a non-blank human-readable
    string. Raised before any connection is opened (URL policy) or before
    any response body byte is read (redirect policy)."""

    def __init__(self, reason_code: str, reason: str) -> None:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("ExactSourceTransportPolicyError requires a non-blank reason")
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def _load_registered_contract() -> dict[str, str]:
    """Read the pinned `dataset_registration.exact_url` fresh from the
    registration spec -- never cached, never defaulted, never supplied by
    a caller. Raises `ExactSourceTransportError` (never a policy error) if
    the spec is missing or malformed: a broken pin is a configuration
    failure, not a per-call policy rejection."""
    try:
        raw = _REGISTRATION_SPEC_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise ExactSourceTransportError(f"unable to read registration spec: {exc}") from exc
    try:
        loaded = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ExactSourceTransportError(f"registration spec is not valid YAML: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ExactSourceTransportError("registration spec must parse to a mapping")
    dataset_registration = loaded.get("dataset_registration")
    if not isinstance(dataset_registration, dict):
        raise ExactSourceTransportError("registration spec missing dataset_registration mapping")
    registered_url = str(dataset_registration.get("exact_url"))
    parsed = urlsplit(registered_url)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.path:
        raise ExactSourceTransportError("registered exact_url must be an https URL with a host and a path")
    return {
        "registered_url": registered_url,
        "registered_host": parsed.hostname,
        "registered_path": parsed.path,
    }


def _first_header(raw_headers: Any, name: str) -> str | None:
    name_lower = name.lower()
    if not isinstance(raw_headers, list):
        return None
    for entry in raw_headers:
        if isinstance(entry, (list, tuple)) and len(entry) == 2 and str(entry[0]).lower() == name_lower:
            return str(entry[1])
    return None


def _require_timeout(value: float, *, label: str) -> float:
    numeric = float(value)
    if not (_MIN_TIMEOUT_SECONDS < numeric <= _MAX_TIMEOUT_SECONDS):
        raise ValueError(f"{label} must be > {_MIN_TIMEOUT_SECONDS} and <= {_MAX_TIMEOUT_SECONDS}, got {value!r}")
    return numeric


class _ExactSourceTransport:
    """The injected `transport` port `execute_transport_and_raw_freeze`
    calls: `head(url)` / `stream_get(url, chunk_bytes)`. Never constructed
    directly -- use `build_transport`."""

    def __init__(
        self,
        *,
        connection_factory: Callable[..., Any],
        socket_module: Any,
        tls_context_factory: Callable[[], Any],
        head_timeout_seconds: float,
        get_timeout_seconds: float,
        max_chunk_bytes: int,
    ) -> None:
        self._connection_factory = connection_factory
        #: Never called by this class -- accepted purely as an offline-test
        #: injection point (a fake that raises on `.socket()`/
        #: `.create_connection()` proves this transport never opens a raw
        #: socket itself; every connection goes through `connection_factory`).
        self._socket_module = socket_module
        self._tls_context_factory = tls_context_factory
        self._head_timeout_seconds = _require_timeout(head_timeout_seconds, label="head_timeout_seconds")
        self._get_timeout_seconds = _require_timeout(get_timeout_seconds, label="get_timeout_seconds")
        self._max_chunk_bytes = min(int(max_chunk_bytes), _ABSOLUTE_MAX_CHUNK_BYTES)

    def _validated_target(self, url: str) -> dict[str, str]:
        contract = _load_registered_contract()
        if url != contract["registered_url"]:
            raise ExactSourceTransportPolicyError(
                URL_POLICY_REASON, f"url is not the exact registered archive URL: {url!r}"
            )
        return contract

    def head(self, url: str) -> dict[str, Any]:
        contract = self._validated_target(url)
        context = self._tls_context_factory()
        conn = self._connection_factory(
            contract["registered_host"], timeout=self._head_timeout_seconds, context=context
        )
        try:
            conn.request("HEAD", contract["registered_path"], headers={})
            response = conn.getresponse()
            raw_headers = list(response.getheaders())
            location = _first_header(raw_headers, "location")
            final_url = location if location is not None else url
            return {
                "status_code": int(response.status),
                "final_url": final_url,
                "raw_headers": raw_headers,
            }
        finally:
            conn.close()

    def stream_get(self, url: str, chunk_bytes: int) -> Iterator[bytes]:
        contract = self._validated_target(url)
        effective_chunk = min(int(chunk_bytes), self._max_chunk_bytes)
        if effective_chunk <= 0:
            effective_chunk = 1
        context = self._tls_context_factory()
        conn = self._connection_factory(
            contract["registered_host"], timeout=self._get_timeout_seconds, context=context
        )
        try:
            conn.request("GET", contract["registered_path"], headers={})
            response = conn.getresponse()
            if int(response.status) in _REDIRECT_STATUS_CODES:
                location = _first_header(response.getheaders(), "location")
                raise ExactSourceTransportPolicyError(
                    REDIRECT_POLICY_REASON,
                    f"archive GET redirected (status={response.status}, location={location!r}); "
                    "no redirect is ever followed, on- or off-host/path alike",
                )
            while True:
                chunk = response.read(effective_chunk)
                if not chunk:
                    break
                yield chunk
        finally:
            conn.close()


def build_transport(
    *,
    connection_factory: Callable[..., Any] = http.client.HTTPSConnection,
    socket_module: Any = None,
    tls_context_factory: Callable[[], Any] = ssl.create_default_context,
    head_timeout_seconds: float = 30,
    get_timeout_seconds: float = 60,
    max_chunk_bytes: int = MAX_DOWNLOAD_CHUNK_BYTES,
) -> _ExactSourceTransport:
    """Build the ADR-0020 `clinvar-2026-08-amendment-v2` exact-single-source
    HTTPS transport. Every hook is injectable (`connection_factory`,
    `socket_module`, `tls_context_factory`) so offline tests never open a
    real socket; the defaults (`http.client.HTTPSConnection`,
    `ssl.create_default_context` -- TLS verification always on) are the
    only real network path this module ever provides. `max_chunk_bytes` is
    always further clamped to an absolute 8 MiB ceiling regardless of what
    is requested here or per-call."""
    return _ExactSourceTransport(
        connection_factory=connection_factory,
        socket_module=socket_module,
        tls_context_factory=tls_context_factory,
        head_timeout_seconds=head_timeout_seconds,
        get_timeout_seconds=get_timeout_seconds,
        max_chunk_bytes=max_chunk_bytes,
    )
