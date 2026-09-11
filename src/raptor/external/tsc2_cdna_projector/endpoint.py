"""HTTPS endpoint construction and allowlist validation for the cliPE cDNA
-> GRCh38 SPDI projector (NCBI Variation Services, ``/variation/v0``).

This module never performs network I/O itself. URL builders percent-encode
the ENTIRE ``{hgvs}``/``{spdi}`` path segment with ``urllib.parse.quote``
(``safe=''`` -- no "safe" characters, so a caller-supplied HGVS/SPDI string
can never smuggle an extra path segment or query parameter) exactly as the
spec's ``api.endpoint_sequence.*.path_binding.encoding`` rule requires.

``assert_allowed_projector_final_url`` enforces the spec's
``network_boundary`` rule: only HTTPS, only ``api.ncbi.nlm.nih.gov``, only
the three fixed step1/step2/step3 path templates, an EMPTY query string on
both the requested and final URL, and the exact same decoded path
resource between ``requested_url`` and ``final_url`` (no transcript/allele
substitution via redirect) are ever acceptable. The unstable
``/hgvs/batch/contextuals`` endpoint and the nonexistent direct
``/hgvs/{hgvs}/canonical_representative`` path are explicitly rejected
even though the latter would otherwise structurally resemble an allowed
``contextuals`` path with a literal ``batch`` resource segment.

``fetch_raw_with_transport``/``fetch_with_transport`` are the only places a
fetch result crosses into this package, and they only ever call the
*injected* ``transport`` callable; the real network call, if any, always
originates in the caller (``scripts/fetch_tsc2_clipe_cdna_spdi_projector.py``),
never here. ``fetch_raw_with_transport`` validates a transport result's
shape/types (a mapping with a nonblank string ``final_url``, an integer
``http_status``, a nonblank string ``media_type`` and a ``bytes`` ``body``)
WITHOUT constraining the numeric status -- the caller (``ingest.py``)
still needs the actual HTTP status (200, a retryable 5xx, or a permanent
4xx) to drive its own retry/row-failure decisions. ``fetch_with_transport``
is the same validation PLUS a hard requirement that ``http_status == 200``
-- the contract this package's own tests exercise directly. A raised
transport exception, a non-mapping result, or a result missing/mistyping
a required field becomes a typed ``ProjectorTransportValidationError`` in
both cases; neither function ever echoes an underlying transport
exception's own message text (which may carry a secret/signed query
value), only its exception type name.
"""
from __future__ import annotations

import hashlib
from typing import Any, Callable
from urllib.parse import quote, urlsplit

BASE_URL = "https://api.ncbi.nlm.nih.gov/variation/v0"
EXPECTED_HOST = "api.ncbi.nlm.nih.gov"
EXPECTED_BASE_PATH = "/variation/v0"

#: Path templates this package is ever allowed to request or accept as a
#: ``final_url``, keyed by step name; ``{resource}`` is the single,
#: percent-encoded HGVS/SPDI path segment.
_STEP1_PATH_PREFIX = "/variation/v0/hgvs/"
_STEP1_PATH_SUFFIX = "/contextuals"
_STEP2_PATH_PREFIX = "/variation/v0/spdi/"
_STEP2_PATH_SUFFIX = "/canonical_representative"
_STEP3_PATH_PREFIX = "/variation/v0/spdi/"
_STEP3_PATH_SUFFIX = "/hgvs"

#: The unstable/nonexistent endpoints this contract forbids outright (spec
#: ``api.rejected_endpoints``) -- checked BEFORE the generic step1 template
#: match, since ``/hgvs/batch/contextuals`` would otherwise structurally
#: match the step1 template with a literal ``batch`` resource segment.
_FORBIDDEN_BATCH_CONTEXTUALS_PATH = "/variation/v0/hgvs/batch/contextuals"


class ProjectorEndpointSecurityError(ValueError):
    """Raised when a URL's scheme, host, or path template falls outside
    the fixed projector allowlist, when it uses a forbidden endpoint
    (batch contextuals, direct hgvs canonical_representative), when it
    carries a non-empty query string, or when a ``final_url`` substitutes
    a different path template/resource/query than the ``requested_url``
    (endpoint or resource substitution via redirect)."""


class ProjectorTransportValidationError(ValueError):
    """Raised when an injected ``transport`` callable raises (the
    underlying transport exception's own message is never echoed here --
    only its exception type name -- since it may carry a secret this
    package must never surface verbatim), or when its returned result is
    not a mapping with a nonblank string ``final_url``, an integer HTTP
    status, a nonblank string ``media_type`` and a ``bytes`` ``body``
    (``fetch_with_transport`` additionally requires that status be exactly
    ``200``)."""


def build_step1_hgvs_contextuals_url(*, hgvs_c: str) -> str:
    """Build the step1 ``GET /hgvs/{hgvs}/contextuals`` URL, percent-
    encoding the entire ``hgvs_c`` path segment (``quote(hgvs_c, safe='')``
    -- at minimum ``:`` -> ``%3A`` and ``>`` -> ``%3E``)."""
    return f"{BASE_URL}/hgvs/{quote(hgvs_c, safe='')}/contextuals"


def build_step2_spdi_canonical_representative_url(*, spdi: str) -> str:
    """Build the step2 ``GET /spdi/{spdi}/canonical_representative`` URL,
    percent-encoding the entire ``spdi`` path segment (``quote(spdi,
    safe='')``)."""
    return f"{BASE_URL}/spdi/{quote(spdi, safe='')}/canonical_representative"


def build_step3_spdi_hgvs_url(*, spdi: str) -> str:
    """Build the OPTIONAL step3 ``GET /spdi/{spdi}/hgvs`` URL, percent-
    encoding the entire ``spdi`` path segment (``quote(spdi, safe='')``).
    Acquisition success never requires this step to succeed."""
    return f"{BASE_URL}/spdi/{quote(spdi, safe='')}/hgvs"


def _classify_and_validate_path(url: str, *, role: str) -> tuple[str, str]:
    """Validate ``url``'s scheme/host/query and path template against the
    fixed projector allowlist, returning ``(step, encoded_resource)``.
    Raises ``ProjectorEndpointSecurityError`` on any violation, including
    the two explicitly forbidden endpoints (batch contextuals, direct
    hgvs canonical_representative) even though the former would otherwise
    structurally match the step1 template."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise ProjectorEndpointSecurityError(f"{role} scheme is not https: {parts.scheme!r} ({url!r})")
    if parts.netloc != EXPECTED_HOST:
        raise ProjectorEndpointSecurityError(
            f"{role} host is not in the projector allowlist: {parts.netloc!r} ({url!r})"
        )
    if parts.query != "":
        raise ProjectorEndpointSecurityError(
            f"{role} must not carry a query string for a projector endpoint: {parts.query!r} ({url!r})"
        )

    path = parts.path
    if path == _FORBIDDEN_BATCH_CONTEXTUALS_PATH:
        raise ProjectorEndpointSecurityError(
            f"{role} uses the forbidden, unstable batch contextuals endpoint: {path!r}"
        )
    if path.startswith(_STEP1_PATH_PREFIX) and path.endswith("/canonical_representative"):
        raise ProjectorEndpointSecurityError(
            f"{role} uses the forbidden direct hgvs canonical_representative endpoint "
            f"(no such path exists on this API): {path!r}"
        )

    for step, prefix, suffix in (
        ("step1", _STEP1_PATH_PREFIX, _STEP1_PATH_SUFFIX),
        ("step2", _STEP2_PATH_PREFIX, _STEP2_PATH_SUFFIX),
        ("step3", _STEP3_PATH_PREFIX, _STEP3_PATH_SUFFIX),
    ):
        if path.startswith(prefix) and path.endswith(suffix):
            resource = path[len(prefix) : len(path) - len(suffix)]
            if resource and "/" not in resource:
                return step, resource

    raise ProjectorEndpointSecurityError(
        f"{role} path is not an allowed projector endpoint template: {path!r}"
    )


def assert_allowed_projector_final_url(*, requested_url: str, final_url: str) -> None:
    """Validate both the URL this package requested and the (possibly
    redirected) ``final_url`` a transport reports back against the fixed
    projector allowlist (see module docstring). Beyond each URL being
    independently allowlisted, ``final_url`` must retain the exact same
    step (path template) and the exact same percent-encoded resource
    segment as ``requested_url`` -- a redirect that changes the endpoint
    (e.g. ``contextuals`` -> ``canonical_representative``), substitutes a
    different HGVS/SPDI resource, or adds a query parameter (e.g. a
    smuggled ``api_key``) is endpoint/resource substitution and is never
    acceptable, even though both endpoints may be individually
    allowlisted."""
    requested_step, requested_resource = _classify_and_validate_path(requested_url, role="requested_url")
    final_step, final_resource = _classify_and_validate_path(final_url, role="final_url")

    if requested_step != final_step:
        raise ProjectorEndpointSecurityError(
            f"final_url step {final_step!r} does not match the requested step {requested_step!r} "
            "(endpoint substitution across allowlisted projector paths)"
        )
    if requested_resource != final_resource:
        raise ProjectorEndpointSecurityError(
            "final_url resource does not match the requested_url resource (possible allele/"
            f"transcript substitution via redirect): requested={requested_resource!r} "
            f"final={final_resource!r}"
        )


def _validate_transport_result(response: Any, *, requested_url: str) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise ProjectorTransportValidationError(
            f"transport response is not a mapping: {type(response).__name__}"
        )
    for field in ("final_url", "http_status", "media_type", "body"):
        if field not in response:
            raise ProjectorTransportValidationError(
                f"transport response is missing required field {field!r}"
            )

    final_url = response["final_url"]
    http_status = response["http_status"]
    media_type = response["media_type"]
    body = response["body"]

    if not isinstance(final_url, str) or not final_url.strip():
        raise ProjectorTransportValidationError(
            f"transport response final_url is not a nonblank string (type "
            f"{type(final_url).__name__}; value withheld -- it may carry a signed/secret "
            "query value)"
        )
    if not isinstance(http_status, int) or isinstance(http_status, bool):
        raise ProjectorTransportValidationError(
            f"transport response http_status is not an int: {type(http_status).__name__}"
        )
    if not isinstance(media_type, str) or not media_type.strip():
        raise ProjectorTransportValidationError(
            f"transport response media_type is not a nonblank string: {media_type!r}"
        )
    if not isinstance(body, bytes):
        raise ProjectorTransportValidationError(
            f"transport response body is not bytes: {type(body).__name__}"
        )

    return {
        "requested_url": requested_url,
        "final_url": final_url,
        "http_status": http_status,
        "media_type": media_type,
        "body": body,
        "byte_length": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def fetch_raw_with_transport(
    *,
    requested_url: str,
    transport: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    """Call the injected ``transport(requested_url)`` and validate the
    shape/types of its returned result (see module docstring), WITHOUT
    constraining ``http_status`` to ``200`` -- the caller still needs the
    actual status to drive retry/row-failure decisions. Raises
    ``ProjectorTransportValidationError`` if ``transport`` itself raises
    (its own message is never echoed, only its exception type name), or if
    its result fails shape/type validation."""
    try:
        response = transport(requested_url)
    except Exception as exc:  # noqa: BLE001 - any transport exception becomes a typed error
        raise ProjectorTransportValidationError(
            f"transport call raised {type(exc).__name__} (the requested URL and the "
            "underlying transport exception message are both withheld from this message to "
            "avoid leaking transport-layer secrets)"
        ) from exc
    return _validate_transport_result(response, requested_url=requested_url)


def fetch_with_transport(
    *,
    requested_url: str,
    transport: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    """``fetch_raw_with_transport`` PLUS a hard requirement that
    ``http_status`` is exactly the integer ``200`` -- raises
    ``ProjectorTransportValidationError`` otherwise."""
    result = fetch_raw_with_transport(requested_url=requested_url, transport=transport)
    if result["http_status"] != 200:
        raise ProjectorTransportValidationError(
            f"transport response http_status is not exactly the integer 200: "
            f"{result['http_status']!r}"
        )
    return result


__all__ = [
    "BASE_URL",
    "EXPECTED_HOST",
    "EXPECTED_BASE_PATH",
    "ProjectorEndpointSecurityError",
    "ProjectorTransportValidationError",
    "build_step1_hgvs_contextuals_url",
    "build_step2_spdi_canonical_representative_url",
    "build_step3_spdi_hgvs_url",
    "assert_allowed_projector_final_url",
    "fetch_raw_with_transport",
    "fetch_with_transport",
]
