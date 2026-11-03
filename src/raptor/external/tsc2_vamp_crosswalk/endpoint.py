"""HTTPS endpoint construction and allowlist validation for the VAMP-seq
genomic crosswalk's single Zenodo archive download (record 20837254).

This module never performs network I/O itself. ``build_zenodo_archive_
download_url`` percent-encodes the filename PATH segment with ``safe='/'``
(a Zenodo file path is itself a POSIX-style relative path, e.g.
``FowlerLab/TSC2_analysis-V1.zip`` -- its internal ``/`` separators are
never percent-encoded, only characters that would otherwise be
ambiguous/unsafe are).

``assert_allowed_zenodo_final_url`` enforces the spec's network-boundary
rule: only HTTPS, only ``zenodo.org``, only the fixed
``/api/records/{record_id}/files/{filename}/content`` template, an EMPTY
query string on both the requested and final URL, and the exact same
``record_id``/``filename`` between ``requested_url`` and ``final_url`` (no
record/file substitution via redirect) are ever acceptable.

``fetch_with_transport`` is the only place a fetch result crosses into
this package, and it only ever calls the *injected* ``transport``
callable; the real network call, if any, always originates in the caller
(``scripts/fetch_tsc2_vamp_genomic_crosswalk.py``), never here. A raised
transport exception, a non-mapping result, or a result missing/mistyping
a required field becomes a typed ``VampCrosswalkTransportValidationError``;
the underlying transport exception's own message is never echoed, only
its exception type name.
"""
from __future__ import annotations

import hashlib
from typing import Any, Callable
from urllib.parse import quote, urlsplit

ZENODO_HOST = "zenodo.org"
_PATH_PREFIX = "/api/records/"
_PATH_MIDDLE = "/files/"
_PATH_SUFFIX = "/content"


class VampCrosswalkEndpointSecurityError(ValueError):
    """Raised when a URL's scheme, host, or path template falls outside
    the fixed Zenodo allowlist, when it carries a non-empty query string,
    or when a ``final_url`` substitutes a different ``record_id``/
    ``filename`` than the ``requested_url`` (redirect-based resource
    substitution)."""


class VampCrosswalkTransportValidationError(ValueError):
    """Raised when an injected ``transport`` callable raises (its own
    message is never echoed -- only its exception type name, since it may
    carry a secret this package must never surface verbatim), or when its
    returned result is not a mapping with a nonblank string ``final_url``,
    an integer HTTP status exactly ``200``, a nonblank string
    ``media_type`` and a ``bytes`` ``body``."""


def build_zenodo_archive_download_url(*, record_id: int, filename: str) -> str:
    """Build the Zenodo archive-content download URL for one
    ``record_id``/``filename`` pair. ``filename`` is percent-encoded with
    ``safe='/'`` -- its internal path separators are preserved literally,
    matching Zenodo's own file-path URL convention, while any other
    unsafe/ambiguous character is still escaped."""
    encoded_filename = quote(filename, safe="/")
    return f"https://{ZENODO_HOST}{_PATH_PREFIX}{record_id}{_PATH_MIDDLE}{encoded_filename}{_PATH_SUFFIX}"


def _classify_zenodo_path(url: str, *, role: str) -> tuple[str, str]:
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise VampCrosswalkEndpointSecurityError(f"{role} scheme is not https: {parts.scheme!r} ({url!r})")
    if parts.netloc != ZENODO_HOST:
        raise VampCrosswalkEndpointSecurityError(f"{role} host is not zenodo.org: {parts.netloc!r} ({url!r})")
    if parts.query != "":
        raise VampCrosswalkEndpointSecurityError(
            f"{role} must not carry a query string for the archive download endpoint: {parts.query!r} ({url!r})"
        )
    path = parts.path
    if not path.startswith(_PATH_PREFIX) or not path.endswith(_PATH_SUFFIX) or _PATH_MIDDLE not in path:
        raise VampCrosswalkEndpointSecurityError(
            f"{role} path is not the allowed Zenodo archive-download template: {path!r}"
        )
    remainder = path[len(_PATH_PREFIX) :]
    record_part, _, rest = remainder.partition(_PATH_MIDDLE)
    if not record_part or not rest.endswith(_PATH_SUFFIX):
        raise VampCrosswalkEndpointSecurityError(
            f"{role} path is not the allowed Zenodo archive-download template: {path!r}"
        )
    filename_part = rest[: -len(_PATH_SUFFIX)]
    if not filename_part:
        raise VampCrosswalkEndpointSecurityError(f"{role} path is missing a filename resource: {path!r}")
    return record_part, filename_part


def assert_allowed_zenodo_final_url(*, requested_url: str, final_url: str) -> None:
    """Validate both the URL this package requested and the (possibly
    redirected) ``final_url`` a transport reports back against the fixed
    Zenodo archive-download allowlist. ``final_url`` must retain the exact
    same ``record_id`` and (percent-encoded) ``filename`` as
    ``requested_url`` -- a redirect that substitutes a different Zenodo
    record or a different archive filename (e.g. a later version) is
    resource substitution and is never acceptable."""
    requested_record, requested_filename = _classify_zenodo_path(requested_url, role="requested_url")
    final_record, final_filename = _classify_zenodo_path(final_url, role="final_url")
    if requested_record != final_record or requested_filename != final_filename:
        raise VampCrosswalkEndpointSecurityError(
            "final_url substitutes a different Zenodo record/filename than the requested_url: "
            f"requested=({requested_record!r}, {requested_filename!r}) final=({final_record!r}, {final_filename!r})"
        )


def _validate_transport_result(response: Any, *, requested_url: str) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise VampCrosswalkTransportValidationError(
            f"transport response is not a mapping: {type(response).__name__}"
        )
    for field_name in ("final_url", "http_status", "media_type", "body"):
        if field_name not in response:
            raise VampCrosswalkTransportValidationError(
                f"transport response is missing required field {field_name!r}"
            )

    final_url = response["final_url"]
    http_status = response["http_status"]
    media_type = response["media_type"]
    body = response["body"]

    if not isinstance(final_url, str) or not final_url.strip():
        raise VampCrosswalkTransportValidationError(
            f"transport response final_url is not a nonblank string (type {type(final_url).__name__}; "
            "value withheld -- it may carry a signed/secret query value)"
        )
    if not isinstance(http_status, int) or isinstance(http_status, bool) or http_status != 200:
        raise VampCrosswalkTransportValidationError(
            f"transport response http_status is not exactly the integer 200: {http_status!r}"
        )
    if not isinstance(media_type, str) or not media_type.strip():
        raise VampCrosswalkTransportValidationError(
            f"transport response media_type is not a nonblank string: {media_type!r}"
        )
    if not isinstance(body, bytes):
        raise VampCrosswalkTransportValidationError(f"transport response body is not bytes: {type(body).__name__}")

    return {
        "requested_url": requested_url,
        "final_url": final_url,
        "http_status": http_status,
        "media_type": media_type,
        "body": body,
        "byte_length": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def fetch_with_transport(*, requested_url: str, transport: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
    """Call the injected ``transport(requested_url)`` -- the only place a
    real network call may originate, and it never originates from this
    package itself -- validate the shape/types of its returned result
    (see module docstring), and return a hashed fetch record
    (``requested_url``, ``final_url``, ``http_status``, ``media_type``,
    ``body``, ``byte_length``, ``sha256``). Raises
    ``VampCrosswalkTransportValidationError`` if ``transport`` itself
    raises (its own message is never echoed, only its exception type
    name), or if its result fails shape/type validation."""
    try:
        response = transport(requested_url)
    except Exception as exc:  # noqa: BLE001 - any transport exception becomes a typed error
        raise VampCrosswalkTransportValidationError(
            f"transport call raised {type(exc).__name__} (the requested URL and the underlying "
            "transport exception message are both withheld from this message to avoid leaking "
            "transport-layer secrets)"
        ) from exc
    return _validate_transport_result(response, requested_url=requested_url)


__all__ = [
    "ZENODO_HOST",
    "VampCrosswalkEndpointSecurityError",
    "VampCrosswalkTransportValidationError",
    "build_zenodo_archive_download_url",
    "assert_allowed_zenodo_final_url",
    "fetch_with_transport",
]
