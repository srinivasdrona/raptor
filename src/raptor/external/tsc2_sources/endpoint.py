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
redirect. `request_with_transport` is the only place a fetch result crosses
into this package, and it only ever calls the *injected* `transport`
callable; the real network call, if any, always originates in the caller
(`scripts/fetch_tsc2_source_bundle.py`), never here.
"""
from __future__ import annotations

import hashlib
from typing import Any, Callable
from urllib.parse import quote, urlencode, urlsplit

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


class EndpointSecurityError(ValueError):
    """Raised when a URL's scheme, or its (host, path), falls outside the
    fixed HTTPS allowlist for TSC2 literature sources."""


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
    publication-date window (`mindate`/`maxdate`), requesting JSON."""
    params = {
        "db": PUBMED_DATABASE,
        "term": query,
        "retmode": "json",
        "mindate": date_start,
        "maxdate": date_end,
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


def assert_allowed_final_url(*, requested_url: str, final_url: str) -> None:
    """Validate both the URL this package requested and the (possibly
    redirected) `final_url` a transport reports back against the fixed
    HTTPS (host, path) allowlist. A redirect target is never trusted purely
    because the request that produced it was trusted. Beyond each URL being
    independently allowlisted, `final_url` must also retain the exact same
    scheme, host and path as `requested_url`: a redirect from one
    allowlisted service/path to a *different* allowlisted service/path
    (e.g. PubMed ESearch -> LitVar2) is endpoint substitution and is never
    acceptable, even though both endpoints are individually trusted. Query
    string differences (e.g. Entrez appending tracking/session parameters)
    are not service identity and are therefore not compared here."""
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


def request_with_transport(
    *,
    requested_url: str,
    transport: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    """Call the injected `transport(requested_url)` -- the only place a real
    network call may originate, and it never originates from this package
    itself -- validate the reported `final_url` against the allowlist, and
    return a hashed fetch record (`requested_url`, `final_url`,
    `http_status`, `media_type`, `body`, `byte_length`, `sha256`)."""
    response = transport(requested_url)
    final_url = response["final_url"]
    assert_allowed_final_url(requested_url=requested_url, final_url=final_url)
    body = response["body"]
    return {
        "requested_url": requested_url,
        "final_url": final_url,
        "http_status": response["http_status"],
        "media_type": response["media_type"],
        "body": body,
        "byte_length": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


__all__ = [
    "EndpointSecurityError",
    "PUBMED_ESEARCH_URL",
    "PUBMED_EFETCH_URL",
    "LITVAR2_GENE_SEARCH_BASE",
    "PUBMED_DATABASE",
    "ALLOWED_HTTPS_ENDPOINTS",
    "build_pubmed_esearch_url",
    "build_pubmed_efetch_url",
    "build_litvar2_gene_url",
    "assert_allowed_final_url",
    "request_with_transport",
]
