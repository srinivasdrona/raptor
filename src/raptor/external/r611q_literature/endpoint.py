"""HTTPS endpoint construction and allowlist validation for the R611Q
literature-expansion sources (NCBI LitVar2, NCBI Entrez E-utilities/
PubMed, Europe PMC).

This module never performs network I/O itself. URL builders percent-encode
every dynamic value with `urllib.parse.quote` (`%20` for spaces, never
`+`, and no "safe" characters) so a caller-supplied variant/PMID/PMCID
value can never smuggle an extra query parameter or change the request's
scheme/host/path. `assert_allowed_final_url` enforces the fixed, small
HTTPS (host, path) allowlist this literature-only slice ever needs -- both
for the URL this package built and for the `final_url` a transport reports
back after following any redirect -- and additionally binds every
canonical, source-defining query parameter between the requested and final
URL (e.g. E-utilities' `id`/`term`/`retmax`, Europe PMC's `query`): a
redirect may never silently substitute a different PMID set, search term
or query. Only explicitly nonsemantic query parameters (outside that
canonical set) may differ.

`request_with_transport` is the only place a fetch result crosses into
this package, and it only ever calls the *injected* `transport` callable;
the real network call, if any, always originates in the caller
(`scripts/fetch_r611q_literature_expansion.py`), never here. Every
transport call is wrapped: a raised transport exception, a non-mapping
result, or a result missing/mistyping its required `final_url`/
`http_status`/`media_type`/`body` fields becomes a typed
`TransportValidationError` -- this module never lets a raw/untyped
transport exception (or a malformed transport result) escape as-is, and it
never echoes an underlying transport exception's own message text (which
may carry a secret), only its exception type name. This wraps
`raptor.external.tsc2_sources.endpoint.fetch_with_transport` directly --
the shape/type validation rules for a transport result are identical
across both literature-source packages, so they are shared rather than
re-implemented.
"""
from __future__ import annotations

from typing import Any, Callable
from urllib.parse import parse_qs, quote, urlencode, urlsplit

from raptor.external.tsc2_sources.endpoint import (
    EndpointSecurityError,
    TransportValidationError,
    fetch_with_transport,
)

LITVAR_PUBLICATIONS_BASE = (
    "https://www.ncbi.nlm.nih.gov/research/litvar2-api/variant/get"
)
CLINVAR_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
CLINVAR_ELINK_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi"
PUBMED_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
EUROPE_PMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
EUROPE_PMC_SEARCH_URL = f"{EUROPE_PMC_BASE}/search"

#: Fixed (host, path) pairs this package is ever allowed to request or
#: accept as a `final_url`. A path ending in "/" is prefix-matched (the
#: LitVar2 percent-encoded variant id and an Europe PMC PMCID are appended
#: by the caller); every other path requires an exact match.
ALLOWED_HTTPS_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("www.ncbi.nlm.nih.gov", "/research/litvar2-api/variant/get/"),
    ("eutils.ncbi.nlm.nih.gov", "/entrez/eutils/esearch.fcgi"),
    ("eutils.ncbi.nlm.nih.gov", "/entrez/eutils/elink.fcgi"),
    ("eutils.ncbi.nlm.nih.gov", "/entrez/eutils/efetch.fcgi"),
    ("www.ebi.ac.uk", "/europepmc/webservices/rest/"),
)

#: Canonical, source-defining query parameters that a redirect's `final_url`
#: may never silently substitute, keyed by the exact (host, path) it
#: applies to. Any query parameter NOT listed here is explicitly
#: nonsemantic and may differ freely between `requested_url` and
#: `final_url`. Endpoints not present in this mapping (LitVar2, Europe PMC
#: full-text-by-PMCID) carry no query-string identity of their own -- their
#: identity is already bound via the path itself, and the generic
#: full-query-string-equality fallback in `_assert_no_source_defining_
#: query_substitution` applies instead.
_SOURCE_DEFINING_QUERY_KEYS: dict[tuple[str, str], frozenset[str]] = {
    ("eutils.ncbi.nlm.nih.gov", "/entrez/eutils/esearch.fcgi"): frozenset(
        {"db", "term", "retmode", "retmax"}
    ),
    ("eutils.ncbi.nlm.nih.gov", "/entrez/eutils/elink.fcgi"): frozenset(
        {"dbfrom", "db", "id", "linkname", "retmode"}
    ),
    ("eutils.ncbi.nlm.nih.gov", "/entrez/eutils/efetch.fcgi"): frozenset(
        {"db", "rettype", "retmode", "id"}
    ),
    ("www.ebi.ac.uk", "/europepmc/webservices/rest/search"): frozenset(
        {"query", "resultType", "pageSize", "format"}
    ),
}


def _percent_encode_query(params: dict[str, str]) -> str:
    """Percent-encode a query mapping with `%20` for spaces (never `+`) and
    no "safe" characters, so any value with a slash/bracket/quote is always
    escaped rather than passed through as URL syntax."""
    return urlencode(params, safe="", quote_via=quote)


def build_litvar_publications_url(*, litvar_id: str) -> str:
    """Build the exact LitVar2 "get publications" URL for one variant id
    (e.g. `litvar@rs28934872##`), percent-encoding it as a single path
    segment."""
    return f"{LITVAR_PUBLICATIONS_BASE}/{quote(litvar_id, safe='')}/publications?format=json"


def build_clinvar_esearch_url(*, rsid: str, retmax: int, tool: str) -> str:
    """Build the NCBI Entrez ESearch URL resolving an rsID to its ClinVar
    UID, requesting JSON."""
    params = {
        "db": "clinvar",
        "term": rsid,
        "retmode": "json",
        "retmax": str(retmax),
        "tool": tool,
    }
    return f"{CLINVAR_ESEARCH_URL}?{_percent_encode_query(params)}"


def build_clinvar_elink_url(*, uid: str, tool: str) -> str:
    """Build the NCBI Entrez ELink URL for the `clinvar_pubmed` citation
    links of one ClinVar UID, requesting JSON."""
    params = {
        "dbfrom": "clinvar",
        "db": "pubmed",
        "id": uid,
        "linkname": "clinvar_pubmed",
        "retmode": "json",
        "tool": tool,
    }
    return f"{CLINVAR_ELINK_URL}?{_percent_encode_query(params)}"


def build_pubmed_efetch_url(*, pmids: list[str], tool: str) -> str:
    """Build the NCBI Entrez EFetch URL for a fixed, caller-supplied list of
    PMIDs, requesting abstract-format XML metadata."""
    params = {
        "db": "pubmed",
        "rettype": "abstract",
        "retmode": "xml",
        "tool": tool,
        "id": ",".join(pmids),
    }
    return f"{PUBMED_EFETCH_URL}?{_percent_encode_query(params)}"


def build_europe_pmc_core_url(*, pmids: list[str], page_size: int) -> str:
    """Build the Europe PMC "core" search URL for a fixed, caller-supplied
    list of PMIDs, restricted to the MEDLINE source via `SRC:MED`,
    requesting JSON. The query is built EXACTLY as
    `(EXT_ID:<p1> OR EXT_ID:<p2> ...) AND SRC:MED` -- the PMID disjunction
    grouped first, `SRC:MED` last -- never the reverse grouping."""
    pmid_clause = " OR ".join(f"EXT_ID:{pmid}" for pmid in pmids)
    query = f"({pmid_clause}) AND SRC:MED"
    params = {
        "query": query,
        "resultType": "core",
        "pageSize": str(page_size),
        "format": "json",
    }
    return f"{EUROPE_PMC_SEARCH_URL}?{_percent_encode_query(params)}"


def build_europe_pmc_fulltext_xml_url(*, pmcid: str) -> str:
    """Build the Europe PMC full-text JATS XML URL for one PMCID."""
    return f"{EUROPE_PMC_BASE}/{quote(pmcid, safe='')}/fullTextXML"


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


def _assert_no_source_defining_query_substitution(*, requested_parts, final_parts) -> None:
    canonical_keys = _SOURCE_DEFINING_QUERY_KEYS.get((final_parts.netloc, final_parts.path))
    if canonical_keys is None:
        # No canonical query-key set is registered for this (host, path) --
        # e.g. LitVar2 or an Europe PMC fullTextXML PMCID path, whose
        # identity is bound entirely by path. Fall back to requiring the
        # full query string to match.
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
    HTTPS (host, path) allowlist (`ALLOWED_HTTPS_ENDPOINTS`). A redirect
    target is never trusted purely because the request that produced it
    was trusted. Beyond each URL being independently allowlisted,
    `final_url` must also retain the exact same scheme, host and path as
    `requested_url`: a redirect from one allowlisted service/path to a
    *different* allowlisted service/path is endpoint substitution and is
    never acceptable, even though both endpoints are individually trusted.
    `final_url` must ALSO retain every canonical, source-defining query
    parameter (see `_SOURCE_DEFINING_QUERY_KEYS`) the requested URL carried
    -- e.g. EFetch's `id` (PMID set) or Europe PMC's `query` -- a redirect
    may never silently substitute a different query/PMID-set/UID. Only
    explicitly nonsemantic query parameters outside that canonical set may
    differ."""
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


def request_with_transport(
    *,
    requested_url: str,
    transport: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    """Call the injected `transport(requested_url)` -- the only place a real
    network call may originate, and it never originates from this package
    itself -- validate the shape/types of its returned result (delegated to
    `raptor.external.tsc2_sources.endpoint.fetch_with_transport`), enforce
    this package's own `assert_allowed_final_url` allowlist/query-identity
    check, and return a hashed fetch record (`requested_url`, `final_url`,
    `http_status`, `media_type`, `body`, `byte_length`, `sha256`). Raises
    `TransportValidationError` if `transport` itself raises or its result
    fails shape/type validation, and `EndpointSecurityError` if the
    resulting `final_url` fails this package's endpoint/query-identity
    allowlist."""
    fetched = fetch_with_transport(requested_url=requested_url, transport=transport)
    assert_allowed_final_url(requested_url=requested_url, final_url=fetched["final_url"])
    return fetched


__all__ = [
    "EndpointSecurityError",
    "TransportValidationError",
    "LITVAR_PUBLICATIONS_BASE",
    "CLINVAR_ESEARCH_URL",
    "CLINVAR_ELINK_URL",
    "PUBMED_EFETCH_URL",
    "EUROPE_PMC_BASE",
    "EUROPE_PMC_SEARCH_URL",
    "ALLOWED_HTTPS_ENDPOINTS",
    "build_litvar_publications_url",
    "build_clinvar_esearch_url",
    "build_clinvar_elink_url",
    "build_pubmed_efetch_url",
    "build_europe_pmc_core_url",
    "build_europe_pmc_fulltext_xml_url",
    "assert_allowed_final_url",
    "request_with_transport",
]
