"""HTTPS endpoint construction and allowlist validation for TSC2 literature
sources (NCBI Entrez E-utilities / PubMed, NCBI LitVar2, Europe PMC).

This module never performs network I/O itself. URL builders percent-encode
every query value with `urllib.parse.quote` (`%20` for spaces, never `+`,
and no "safe" characters) so a caller-supplied query term cannot smuggle an
extra query parameter or change the request's scheme/host. `assert_allowed_
final_url` enforces the network boundary described in the spec's
`architecture.network_boundary` rule: only HTTPS and only a fixed set of
(host, path) endpoints are ever acceptable -- both for the URL this package
built and for the `final_url` a transport reports back after following any
redirect. Beyond the fixed (host, path) allowlist, `assert_allowed_final_url`
also binds every canonical, source-defining query parameter (PubMed's
`db`/`term`/`mindate`/`maxdate`/`datetype`/`retmax` for ESearch and
`db`/`id` for EFetch) between the requested and final URL -- a redirect may
never silently substitute a different search query, date window or PMID
set. Only explicitly nonsemantic query parameters (anything outside that
canonical set, e.g. Entrez tracking/session parameters) may differ.

`request_with_transport`/`fetch_with_transport` are the only places a fetch
result crosses into this package, and they only ever call the *injected*
`transport` callable; the real network call, if any, always originates in
the caller (`scripts/fetch_tsc2_source_bundle.py`), never here. Every
transport call is wrapped: a raised transport exception, a non-mapping
result, or a result missing/mistyping its required
`final_url`/`http_status`/`media_type`/`body` fields becomes a typed
`TransportValidationError` -- this module never lets a raw/untyped
transport exception (or a malformed transport result) escape as-is, and it
never echoes an underlying transport exception's own message text (which
may carry a secret), only its exception type name.
"""
from __future__ import annotations

import hashlib
from typing import Any, Callable
from urllib.parse import parse_qs, quote, urlencode, urlsplit

PUBMED_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
LITVAR2_GENE_SEARCH_BASE = (
    "https://www.ncbi.nlm.nih.gov/research/litvar2-api/variant/search/gene"
)
PUBMED_DATABASE = "pubmed"

#: Fixed (host, path) pairs this package is ever allowed to request or
#: accept as a `final_url`. A path ending in "/" is prefix-matched (the
#: LitVar2 gene symbol and an Europe PMC PMCID are appended by the caller);
#: every other path requires an exact match. Functional-dataset hosts
#: (MaveDB, IGVF) are out of scope for this literature-only slice.
ALLOWED_HTTPS_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("eutils.ncbi.nlm.nih.gov", "/entrez/eutils/esearch.fcgi"),
    ("eutils.ncbi.nlm.nih.gov", "/entrez/eutils/efetch.fcgi"),
    ("www.ncbi.nlm.nih.gov", "/research/litvar2-api/variant/search/gene/"),
    ("www.ebi.ac.uk", "/europepmc/webservices/rest/"),
)

#: Canonical, source-defining query parameters that a redirect's `final_url`
#: may never silently substitute, keyed by the exact (host, path) it
#: applies to. Any query parameter NOT listed here is explicitly nonsemantic
#: (e.g. an Entrez tracking/session parameter) and may differ freely between
#: `requested_url` and `final_url`. Endpoints not present in this mapping
#: (LitVar2, Europe PMC) carry no query-string identity of their own -- the
#: gene symbol/PMCID is already bound via the path itself.
_SOURCE_DEFINING_QUERY_KEYS: dict[tuple[str, str], frozenset[str]] = {
    ("eutils.ncbi.nlm.nih.gov", "/entrez/eutils/esearch.fcgi"): frozenset(
        {"db", "term", "mindate", "maxdate", "datetype", "retmax"}
    ),
    ("eutils.ncbi.nlm.nih.gov", "/entrez/eutils/efetch.fcgi"): frozenset({"db", "id"}),
}


class EndpointSecurityError(ValueError):
    """Raised when a URL's scheme, or its (host, path), falls outside the
    fixed HTTPS allowlist for TSC2 literature sources, or when a `final_url`
    substitutes a different canonical source-defining query parameter (see
    `_SOURCE_DEFINING_QUERY_KEYS`) than the one that was requested."""


class TransportValidationError(ValueError):
    """Raised when an injected `transport` callable raises (the underlying
    transport exception's own message is never echoed here -- only its
    exception type name -- since it may carry a secret this package must
    never surface verbatim), or when its returned result is not a mapping
    with a nonblank string `final_url`, an integer HTTP status exactly
    `200`, a nonblank string `media_type` and a `bytes` `body`."""


def _percent_encode_query(params: dict[str, str]) -> str:
    """Percent-encode a query mapping with `%20` for spaces (never `+`,
    which `urlencode`'s default `quote_plus` would emit) and no "safe"
    characters, so slashes/brackets/quotes in a PubMed search term are
    always escaped rather than passed through as URL syntax."""
    return urlencode(params, safe="", quote_via=quote)


def build_pubmed_esearch_url(
    *,
    query: str,
    date_start: str,
    date_end: str,
    retmax: int,
) -> str:
    """Build the NCBI Entrez ESearch URL for a PubMed query bounded to a
    publication-date window (`mindate`/`maxdate`), requesting JSON. Always
    binds `datetype=pdat` (publication date) -- the date window is never
    interpreted against any other NCBI date type (e.g. `edat`)."""
    params = {
        "db": PUBMED_DATABASE,
        "term": query,
        "retmode": "json",
        "mindate": date_start,
        "maxdate": date_end,
        "datetype": "pdat",
        "retmax": str(retmax),
    }
    return f"{PUBMED_ESEARCH_URL}?{_percent_encode_query(params)}"


def build_pubmed_efetch_url(*, pmids: list[str]) -> str:
    """Build the NCBI Entrez EFetch URL for a fixed, caller-supplied list of
    PMIDs, requesting XML metadata."""
    params = {
        "db": PUBMED_DATABASE,
        "id": ",".join(pmids),
        "retmode": "xml",
    }
    return f"{PUBMED_EFETCH_URL}?{_percent_encode_query(params)}"


def build_litvar2_gene_url(*, gene: str) -> str:
    """Build the NCBI LitVar2 gene-search URL for one gene symbol."""
    return f"{LITVAR2_GENE_SEARCH_BASE}/{quote(gene, safe='')}"


def _endpoint_allowed(host: str, path: str) -> bool:
    for allowed_host, allowed_path in ALLOWED_HTTPS_ENDPOINTS:
        if host != allowed_host:
            continue
        if allowed_path.endswith("/"):
            if path.startswith(allowed_path):
                return True
        elif path == allowed_path:
            return True
    return False


def _assert_https_endpoint_allowed(url: str, *, role: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise EndpointSecurityError(
            f"{role} scheme is not in the HTTPS allowlist: {parts.scheme!r} ({url!r})"
        )
    if not _endpoint_allowed(parts.netloc, parts.path):
        raise EndpointSecurityError(
            f"{role} host/path is not in the endpoint allowlist: "
            f"{parts.netloc!r}{parts.path!r}"
        )


def _assert_no_source_defining_query_substitution(
    *, requested_parts, final_parts
) -> None:
    canonical_keys = _SOURCE_DEFINING_QUERY_KEYS.get((final_parts.netloc, final_parts.path))
    if canonical_keys is None:
        # No canonical query-key set is registered for this (host, path) --
        # e.g. LitVar2/Europe PMC, whose identity is bound entirely by path.
        # Fall back to requiring the full query string to match: nothing in
        # this package's literature-source contract EVER needs those
        # endpoints' query strings to legitimately differ across a redirect.
        if parse_qs(requested_parts.query, keep_blank_values=True) != parse_qs(
            final_parts.query, keep_blank_values=True
        ):
            raise EndpointSecurityError(
                "final_url query string does not match the requested_url query string "
                "(possible endpoint substitution)"
            )
        return

    requested_params = parse_qs(requested_parts.query, keep_blank_values=True)
    final_params = parse_qs(final_parts.query, keep_blank_values=True)
    for key in sorted(canonical_keys):
        if requested_params.get(key) != final_params.get(key):
            raise EndpointSecurityError(
                f"final_url source-defining query parameter {key!r} does not match the "
                f"requested_url value (possible endpoint substitution): requested="
                f"{requested_params.get(key)!r} final={final_params.get(key)!r}"
            )


def assert_allowed_final_url(*, requested_url: str, final_url: str) -> None:
    """Validate both the URL this package requested and the (possibly
    redirected) `final_url` a transport reports back against the fixed
    HTTPS (host, path) allowlist. A redirect target is never trusted purely
    because the request that produced it was trusted. Beyond each URL being
    independently allowlisted, `final_url` must also retain the exact same
    scheme, host and path as `requested_url`: a redirect from one
    allowlisted service/path to a *different* allowlisted service/path
    (e.g. PubMed ESearch -> LitVar2) is endpoint substitution and is never
    acceptable, even though both endpoints are individually trusted.
    `final_url` must ALSO retain every canonical, source-defining query
    parameter (see `_SOURCE_DEFINING_QUERY_KEYS`) the requested URL carried
    -- e.g. PubMed's `term`/`mindate`/`maxdate`/`datetype`/`retmax`, or
    EFetch's `id` (PMID set) -- a redirect may never silently substitute a
    different query/date-window/PMID-set. Only explicitly nonsemantic query
    parameters outside that canonical set (e.g. Entrez tracking/session
    parameters) may differ."""
    _assert_https_endpoint_allowed(requested_url, role="requested_url")
    _assert_https_endpoint_allowed(final_url, role="final_url")

    requested_parts = urlsplit(requested_url)
    final_parts = urlsplit(final_url)
    if (
        requested_parts.scheme != final_parts.scheme
        or requested_parts.netloc != final_parts.netloc
        or requested_parts.path != final_parts.path
    ):
        raise EndpointSecurityError(
            "final_url does not match the requested endpoint's scheme/host/path "
            "(endpoint substitution across allowlisted services): "
            f"requested {requested_parts.scheme}://{requested_parts.netloc}"
            f"{requested_parts.path!r} vs final {final_parts.scheme}://"
            f"{final_parts.netloc}{final_parts.path!r}"
        )

    _assert_no_source_defining_query_substitution(
        requested_parts=requested_parts, final_parts=final_parts
    )


def _validate_transport_result(response: Any, *, requested_url: str) -> dict[str, Any]:
    """Validate a transport result's shape/types (see the module docstring)
    and return a hashed fetch record. Raises `TransportValidationError` on
    ANY structural/type violation -- never silently coerces a malformed
    field."""
    if not isinstance(response, dict):
        raise TransportValidationError(
            f"transport response is not a mapping: {type(response).__name__}"
        )

    for field in ("final_url", "http_status", "media_type", "body"):
        if field not in response:
            raise TransportValidationError(
                f"transport response is missing required field {field!r}"
            )

    final_url = response["final_url"]
    http_status = response["http_status"]
    media_type = response["media_type"]
    body = response["body"]

    if not isinstance(final_url, str) or not final_url.strip():
        raise TransportValidationError(
            f"transport response final_url is not a nonblank string (type "
            f"{type(final_url).__name__}; value withheld -- it may carry a signed/secret "
            "query value)"
        )
    if not isinstance(http_status, int) or isinstance(http_status, bool) or http_status != 200:
        raise TransportValidationError(
            f"transport response http_status is not exactly the integer 200: {http_status!r}"
        )
    if not isinstance(media_type, str) or not media_type.strip():
        raise TransportValidationError(
            f"transport response media_type is not a nonblank string: {media_type!r}"
        )
    if not isinstance(body, bytes):
        raise TransportValidationError(
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


def fetch_with_transport(
    *,
    requested_url: str,
    transport: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    """Call the injected `transport(requested_url)` -- the only place a real
    network call may originate, and it never originates from this package
    itself -- validate the shape/types of its returned result (see the
    module docstring), and return a hashed fetch record (`requested_url`,
    `final_url`, `http_status`, `media_type`, `body`, `byte_length`,
    `sha256`). Unlike `request_with_transport`, this does NOT enforce the
    literature-source `ALLOWED_HTTPS_ENDPOINTS` allowlist -- callers with
    their own final-URL identity rules (MaveDB/IGVF) apply those
    separately, right after this returns. Raises `TransportValidationError`
    if `transport` itself raises (its own message is never echoed, only
    its exception type name), or if its result fails shape/type
    validation."""
    try:
        response = transport(requested_url)
    except Exception as exc:  # noqa: BLE001 - any transport exception becomes a typed error
        raise TransportValidationError(
            f"transport call raised {type(exc).__name__} (the requested URL and the "
            "underlying transport exception message are both withheld from this message -- "
            "the caller attaches its own already-sanitized request_url separately -- to "
            "avoid leaking transport-layer secrets)"
        ) from exc
    return _validate_transport_result(response, requested_url=requested_url)


def request_with_transport(
    *,
    requested_url: str,
    transport: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    """`fetch_with_transport` PLUS the literature-source
    `assert_allowed_final_url` allowlist/query-identity check."""
    fetched = fetch_with_transport(requested_url=requested_url, transport=transport)
    assert_allowed_final_url(requested_url=requested_url, final_url=fetched["final_url"])
    return fetched


__all__ = [
    "EndpointSecurityError",
    "TransportValidationError",
    "PUBMED_ESEARCH_URL",
    "PUBMED_EFETCH_URL",
    "LITVAR2_GENE_SEARCH_BASE",
    "PUBMED_DATABASE",
    "ALLOWED_HTTPS_ENDPOINTS",
    "build_pubmed_esearch_url",
    "build_pubmed_efetch_url",
    "build_litvar2_gene_url",
    "assert_allowed_final_url",
    "fetch_with_transport",
    "request_with_transport",
]
