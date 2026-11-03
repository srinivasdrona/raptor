"""R611Q literature-expansion response parsing: baseline discovery-shelf
manifest, LitVar2/ClinVar discovery-lead union/subtraction, PubMed EFetch
XML, Europe PMC "core" JSON, CC BY JATS full text, and the per-lead article
index.

This module performs no network I/O. It reuses the hardened PubMed
partial-date parsing (`raptor.external.tsc2_sources.pubmed`) and JATS
PMCID/licence-paragraph extraction (`raptor.external.tsc2_sources.pmc`)
already committed for the sibling TSC2 source-ingestion package, rather
than re-implementing that logic.

Every parser here fails loud (`R611QLiteratureParseError`) on a malformed
shape, an unexpected/duplicate/extra identifier, or an identity conflict
between two independently-fetched sources -- it never silently drops,
coerces or arbitrarily picks a side. A record explicitly requested but not
returned by PubMed/Europe PMC is reported back to the caller (e.g.
`requested_but_missing_pmids`), never silently dropped and never treated as
a hard failure on its own.
"""
from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from typing import Any

from raptor.external.tsc2_sources.pmc import PmcParseError as _PmcParseError
from raptor.external.tsc2_sources.pmc import _extract_license_text, _extract_pmcid
from raptor.external.tsc2_sources.pubmed import PubMedParseError as _PubMedParseError
from raptor.external.tsc2_sources.pubmed import (
    _element_text,
    _extract_abstract,
    _format_publication_date,
)

ARTICLE_INDEX_SCHEMA = "raptor.external.r611q_literature_article.v1"

_PMID_PATTERN = re.compile(r"^\d+$")
_PMCID_PATTERN = re.compile(r"^PMC\d+$")
_DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)

_KNOWN_EUROPE_PMC_LICENCES = frozenset({"CC BY", "CC BY-NC-ND", "CC BY-NC-SA"})
_KNOWN_OPEN_ACCESS_VALUES = frozenset({"Y", "N"})

#: Fixed, canonical discovery-source order used by `derive_discovery_
#: membership` and `build_article_index_records`. `source_membership`
#: values are always an ordered subset of exactly this tuple.
DISCOVERY_SOURCE_ORDER: tuple[str, ...] = ("litvar2", "clinvar")

_RESTRICTED_CC_ABBREV_PATTERN = re.compile(r"\bBY[\s-]*(NC|ND|SA)\b", re.IGNORECASE)
#: Full-word (and URL-slug) Creative Commons restriction indicators that
#: never carry the short `NC`/`ND`/`SA` abbreviation immediately after
#: `BY` (e.g. `Attribution-NonCommercial`, or a licence URL segment like
#: `/licenses/by-nc/`) -- each maps to the modifier it implies, so a
#: restricted licence expressed in full words or by URL slug is rejected
#: exactly like its abbreviated form.
_RESTRICTED_CC_WORD_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"NON[\s-]*COMMERCIAL", re.IGNORECASE), "NC"),
    (re.compile(r"NO[\s-]*DERIVATIVES?", re.IGNORECASE), "ND"),
    (re.compile(r"SHARE[\s-]*ALIKE", re.IGNORECASE), "SA"),
    (re.compile(r"/BY[\s-]*NC[/\s]", re.IGNORECASE), "NC"),
    (re.compile(r"/BY[\s-]*ND[/\s]", re.IGNORECASE), "ND"),
    (re.compile(r"/BY[\s-]*SA[/\s]", re.IGNORECASE), "SA"),
)
_POSITIVE_CC_BY_PATTERNS = (
    re.compile(r"CREATIVE\s+COMMONS\s+ATTRIBUTION", re.IGNORECASE),
    re.compile(r"CREATIVECOMMONS\.ORG/LICENSES/BY/", re.IGNORECASE),
    re.compile(r"\bCC\s*BY\b", re.IGNORECASE),
)

ARTICLE_INDEX_FIELDS = frozenset(
    {
        "schema",
        "pmid",
        "discovery_sources",
        "pubmed_status",
        "pmcid",
        "doi",
        "title",
        "publication_date",
        "publication_date_precision",
        "abstract",
        "europe_pmc_status",
        "is_open_access",
        "licence",
        "fulltext_status",
        "fulltext_artifact_id",
    }
)


class R611QLiteratureParseError(ValueError):
    """Raised whenever an R611Q literature-expansion source response (or
    the baseline discovery-shelf manifest) cannot be parsed, fails a
    required structural/count validation, carries a duplicate/extra/
    malformed identifier, or conflicts with another already-parsed source
    on a shared PMID's identity (PMCID/DOI)."""


class JatsIdentityError(R611QLiteratureParseError):
    """Raised by `parse_cc_by_jats_fulltext` for a JATS full-text
    document/identity-shape failure: the XML itself is not well-formed,
    `front/article-meta` is missing, the document carries no
    `pmcid` article-id, or that `pmcid` does not match the caller's
    `expected_pmcid`. This is always a hard/fatal failure -- distinct
    from a `JatsLicenceRejectedError`, which is a per-record disposition
    a caller (the operator) is expected to catch and continue past."""


class JatsLicenceRejectedError(R611QLiteratureParseError):
    """Raised by `parse_cc_by_jats_fulltext` when the document's identity
    (PMCID) is fine but its licence declaration is not an unrestricted CC
    BY: the `license-p` paragraph is missing entirely, or it declares a
    restricted Creative Commons variant (`NC`/`ND`/`SA`, in any of their
    abbreviated/full-word/URL-slug forms), or it otherwise never
    explicitly declares CC BY. The operator catches ONLY this subclass
    per full-text candidate (recording a `JATS_LICENCE_REJECTED`
    disposition and continuing to the next candidate) -- it never catches
    the broader `R611QLiteratureParseError` around this call, so a
    `JatsIdentityError` (or any other parse failure) still propagates and
    remains fatal to the whole run."""


def _normalize_doi(value: Any) -> Any:
    if isinstance(value, str):
        return value.lower()
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# ---------------------------------------------------------------------------
# Baseline discovery-shelf manifest
# ---------------------------------------------------------------------------


def parse_baseline_manifest(
    *,
    payload_bytes: bytes,
    expected_schema: str,
    expected_sha256: str,
    expected_byte_length: int,
    expected_pmid_publications: int,
    expected_doi_only_publications: int,
) -> dict[str, Any]:
    """Parse the pinned baseline discovery-shelf manifest (the raw JSON pin
    is validated BEFORE any parsing): its exact byte length and SHA-256
    must match `expected_byte_length`/`expected_sha256`, and its `schema`
    must match `expected_schema`. Each `publications[]` entry's `source_id`
    must be exactly `PMID:<digits>` or `DOI:<doi>` (any other/malformed
    prefix, or a non-numeric PMID, or a non-DOI-shaped DOI, is rejected);
    all other per-publication metadata is allowed and ignored. PMIDs are
    returned sorted numerically; DOIs are lower-cased and returned sorted
    lexicographically. A duplicate PMID (or a DOI that collides only after
    lower-casing) is rejected, as is a publication count that does not
    equal `expected_pmid_publications`/`expected_doi_only_publications`
    exactly."""
    observed_byte_length = len(payload_bytes)
    if observed_byte_length != expected_byte_length:
        raise R611QLiteratureParseError(
            f"baseline manifest byte_length mismatch: expected {expected_byte_length!r}, "
            f"observed {observed_byte_length!r}"
        )
    observed_sha256 = hashlib.sha256(payload_bytes).hexdigest()
    if observed_sha256.lower() != expected_sha256.lower():
        raise R611QLiteratureParseError(
            f"baseline manifest sha256 mismatch: expected {expected_sha256!r}, "
            f"observed {observed_sha256!r}"
        )

    try:
        document = json.loads(payload_bytes)
    except json.JSONDecodeError as exc:
        raise R611QLiteratureParseError(f"baseline manifest is not valid JSON: {exc}") from exc

    if not isinstance(document, dict):
        raise R611QLiteratureParseError(
            f"baseline manifest does not decode to a mapping: {type(document).__name__}"
        )
    schema = document.get("schema")
    if schema != expected_schema:
        raise R611QLiteratureParseError(
            f"baseline manifest schema {schema!r} does not match expected {expected_schema!r}"
        )
    publications = document.get("publications")
    if not isinstance(publications, list):
        raise R611QLiteratureParseError(
            f"baseline manifest 'publications' is missing or malformed: {publications!r}"
        )

    seen_pmids: set[str] = set()
    seen_dois: set[str] = set()
    pmid_publications: list[str] = []
    doi_only_publications: list[str] = []

    for index, publication in enumerate(publications):
        if not isinstance(publication, dict) or "source_id" not in publication:
            raise R611QLiteratureParseError(
                f"baseline manifest publications[{index}] is missing a required 'source_id' "
                f"field: {publication!r}"
            )
        source_id = publication["source_id"]
        if not isinstance(source_id, str):
            raise R611QLiteratureParseError(
                f"baseline manifest publications[{index}] has a malformed source_id: "
                f"{source_id!r}"
            )

        if source_id.startswith("PMID:"):
            candidate = source_id.removeprefix("PMID:")
            if not _PMID_PATTERN.match(candidate):
                raise R611QLiteratureParseError(
                    f"baseline manifest publications[{index}] has a malformed pmid "
                    f"source_id: {source_id!r}"
                )
            if candidate in seen_pmids:
                raise R611QLiteratureParseError(
                    f"baseline manifest has a duplicate pmid source_id: {source_id!r}"
                )
            seen_pmids.add(candidate)
            pmid_publications.append(candidate)
        elif source_id.startswith("DOI:"):
            candidate = source_id.removeprefix("DOI:")
            if not _DOI_PATTERN.match(candidate):
                raise R611QLiteratureParseError(
                    f"baseline manifest publications[{index}] has a malformed doi "
                    f"source_id: {source_id!r}"
                )
            normalized = candidate.lower()
            if normalized in seen_dois:
                raise R611QLiteratureParseError(
                    f"baseline manifest has a duplicate doi source_id (after lower-casing): "
                    f"{source_id!r}"
                )
            seen_dois.add(normalized)
            doi_only_publications.append(normalized)
        else:
            raise R611QLiteratureParseError(
                f"baseline manifest publications[{index}] has an unrecognized source_id "
                f"prefix (expected 'PMID:' or 'DOI:'): {source_id!r}"
            )

    if len(pmid_publications) != expected_pmid_publications:
        raise R611QLiteratureParseError(
            f"baseline manifest pmid_publications count mismatch: expected "
            f"{expected_pmid_publications!r}, observed {len(pmid_publications)!r}"
        )
    if len(doi_only_publications) != expected_doi_only_publications:
        raise R611QLiteratureParseError(
            f"baseline manifest doi_only_publications count mismatch: expected "
            f"{expected_doi_only_publications!r}, observed {len(doi_only_publications)!r}"
        )

    return {
        "schema": schema,
        "raw_sha256": observed_sha256,
        "raw_byte_length": observed_byte_length,
        "pmid_publications": sorted(pmid_publications, key=int),
        "doi_only_publications": sorted(doi_only_publications),
        "counts": {
            "pmid_publications": len(pmid_publications),
            "doi_only_publications": len(doi_only_publications),
        },
    }


# ---------------------------------------------------------------------------
# LitVar2 / ClinVar discovery leads
# ---------------------------------------------------------------------------

_LITVAR_REQUIRED_FIELDS = frozenset({"pmids", "pmcids", "pmids_count"})


def _normalize_litvar_pmid(value: Any) -> str:
    """Normalize one LitVar2 `pmids` entry to its canonical decimal string
    form. LitVar2's real "get publications" response emits `pmids` as
    JSON positive integers (not strings, unlike `pmcids`, which is always
    a `"PMC<digits>"` string) -- this accepts EITHER a genuine positive,
    non-bool int OR an already-decimal string, and normalizes both to the
    same canonical decimal string (so `9101` and `"9101"` collapse to one
    entry when deduplicating). A bool, a non-positive int, any float, or a
    non-decimal string is rejected rather than silently coerced."""
    if isinstance(value, bool):
        raise R611QLiteratureParseError(
            f"litvar publications has a malformed pmid (bool is not accepted): {value!r}"
        )
    if isinstance(value, int):
        if value <= 0:
            raise R611QLiteratureParseError(
                f"litvar publications has a non-positive pmid: {value!r}"
            )
        return str(value)
    if isinstance(value, str):
        if not _PMID_PATTERN.match(value):
            raise R611QLiteratureParseError(
                f"litvar publications has a malformed (non-decimal) pmid: {value!r}"
            )
        return str(int(value))
    raise R611QLiteratureParseError(
        f"litvar publications has a malformed pmid (expected a positive int or a decimal "
        f"string, never a float): {value!r}"
    )


def parse_litvar_publications(payload: str) -> dict[str, Any]:
    """Parse the LitVar2 "get publications" JSON response into
    `{"pmids", "pmcids", "pmid_count", "pmcid_count"}`. Each `pmids` entry
    is normalized via `_normalize_litvar_pmid` (accepting either a JSON
    positive integer -- LitVar2's actual observed shape -- or an
    already-decimal string) to a canonical decimal string BEFORE
    deduplication; `pmcids` entries must already be `"PMC<digits>"`
    strings. `pmids`/`pmcids` are deduplicated preserving first-seen
    order; the payload's `pmids_count` MUST equal the number of unique
    normalized PMIDs (any drift is rejected as a hard parse failure,
    never silently accepted). PMID and PMCID arrays are independent
    discovery sets and are never zipped by index."""
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise R611QLiteratureParseError(f"litvar publications payload is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise R611QLiteratureParseError(
            f"litvar publications payload does not decode to a mapping: {type(document).__name__}"
        )

    keys = set(document)
    if keys != _LITVAR_REQUIRED_FIELDS:
        missing = _LITVAR_REQUIRED_FIELDS - keys
        extra = keys - _LITVAR_REQUIRED_FIELDS
        raise R611QLiteratureParseError(
            "litvar publications payload does not have the exact required fields "
            f"{sorted(_LITVAR_REQUIRED_FIELDS)!r}: missing={sorted(missing)!r} "
            f"extra={sorted(extra)!r}"
        )

    pmids = document["pmids"]
    pmcids = document["pmcids"]
    pmids_count = document["pmids_count"]

    if not isinstance(pmids, list):
        raise R611QLiteratureParseError(f"litvar publications 'pmids' is malformed: {pmids!r}")
    if not isinstance(pmcids, list) or not all(isinstance(v, str) for v in pmcids):
        raise R611QLiteratureParseError(f"litvar publications 'pmcids' is malformed: {pmcids!r}")
    if not isinstance(pmids_count, int) or isinstance(pmids_count, bool):
        raise R611QLiteratureParseError(
            f"litvar publications 'pmids_count' is not an integer: {pmids_count!r}"
        )
    if pmids_count < 0:
        raise R611QLiteratureParseError(
            f"litvar publications 'pmids_count' must not be negative: {pmids_count!r}"
        )

    normalized_pmids = [_normalize_litvar_pmid(v) for v in pmids]
    for pmcid in pmcids:
        if not _PMCID_PATTERN.match(pmcid):
            raise R611QLiteratureParseError(f"litvar publications has a malformed pmcid: {pmcid!r}")

    unique_pmids = list(dict.fromkeys(normalized_pmids))
    unique_pmcids = list(dict.fromkeys(pmcids))

    if pmids_count != len(unique_pmids):
        raise R611QLiteratureParseError(
            f"litvar publications 'pmids_count' {pmids_count!r} does not equal the count of "
            f"unique pmids {len(unique_pmids)!r} (count drift from unique PMID set)"
        )

    return {
        "pmids": unique_pmids,
        "pmcids": unique_pmcids,
        "pmid_count": pmids_count,
        "pmcid_count": len(unique_pmcids),
    }


def parse_clinvar_uid_esearch(payload: str, *, expected_uid: str) -> str:
    """Parse the NCBI Entrez ESearch JSON response resolving an rsID to its
    ClinVar UID, and return that UID. Raises if the expected UID is not
    present in the returned `idlist`, or if the response resolves to more
    than one UID."""
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise R611QLiteratureParseError(f"clinvar esearch payload is not valid JSON: {exc}") from exc
    if not isinstance(document, dict) or "esearchresult" not in document:
        raise R611QLiteratureParseError(
            "clinvar esearch payload is missing the required 'esearchresult' key"
        )
    result = document["esearchresult"]
    if not isinstance(result, dict):
        raise R611QLiteratureParseError(
            f"clinvar esearch 'esearchresult' has a malformed shape: {type(result).__name__}"
        )
    idlist = result.get("idlist")
    if not isinstance(idlist, list) or not all(isinstance(v, str) for v in idlist):
        raise R611QLiteratureParseError(f"clinvar esearch 'idlist' is missing or malformed: {idlist!r}")
    if idlist != [expected_uid]:
        raise R611QLiteratureParseError(
            f"clinvar esearch idlist {idlist!r} does not equal exactly the expected uid "
            f"{[expected_uid]!r}"
        )
    return expected_uid


def parse_clinvar_pubmed_links(payload: str, *, expected_uid: str) -> list[str]:
    """Parse the NCBI Entrez ELink `clinvar_pubmed` citation-links JSON
    response for one ClinVar UID, returning its linked PMIDs deduplicated
    in first-seen order."""
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise R611QLiteratureParseError(f"clinvar elink payload is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise R611QLiteratureParseError(
            f"clinvar elink payload does not decode to a mapping: {type(document).__name__}"
        )
    linksets = document.get("linksets")
    if not isinstance(linksets, list) or len(linksets) != 1:
        raise R611QLiteratureParseError(f"clinvar elink 'linksets' is missing or malformed: {linksets!r}")
    linkset = linksets[0]
    if not isinstance(linkset, dict) or linkset.get("ids") != [expected_uid]:
        raise R611QLiteratureParseError(
            f"clinvar elink linkset ids {linkset.get('ids') if isinstance(linkset, dict) else linkset!r} "
            f"does not equal exactly the expected uid {[expected_uid]!r}"
        )
    linksetdbs = linkset.get("linksetdbs")
    if not isinstance(linksetdbs, list) or not linksetdbs:
        raise R611QLiteratureParseError("clinvar elink linkset is missing 'linksetdbs'")

    links: list[str] = []
    for linksetdb in linksetdbs:
        if (
            not isinstance(linksetdb, dict)
            or linksetdb.get("dbto") != "pubmed"
            or linksetdb.get("linkname") != "clinvar_pubmed"
        ):
            continue
        candidate_links = linksetdb.get("links")
        if not isinstance(candidate_links, list) or not all(isinstance(v, str) for v in candidate_links):
            raise R611QLiteratureParseError(
                f"clinvar elink linksetdb 'links' is malformed: {candidate_links!r}"
            )
        links.extend(candidate_links)

    for pmid in links:
        if not _PMID_PATTERN.match(pmid):
            raise R611QLiteratureParseError(f"clinvar elink has a malformed pmid: {pmid!r}")

    return list(dict.fromkeys(links))


def derive_discovery_membership(
    *,
    litvar_pmids: list[str],
    clinvar_pmids: list[str],
    baseline_pmids: list[str],
) -> dict[str, Any]:
    """Deterministically union the LitVar2/ClinVar discovery-lead PMID sets
    and subtract the already-known baseline PMID set. Returns counts
    (`litvar2_pmids`, `clinvar_pmids`, `intersection_pmids`,
    `union_pmids`), the resulting `new_pmids` (sorted numerically) and a
    `source_membership` mapping (each new PMID -> an ordered subset of
    `DISCOVERY_SOURCE_ORDER` recording which discovery source(s) surfaced
    it). A PMID missing from PubMed/Europe PMC downstream is never
    silently dropped here -- this function only computes discovery-lead
    membership, not resolution status."""
    litvar_set = set(litvar_pmids)
    clinvar_set = set(clinvar_pmids)
    baseline_set = set(baseline_pmids)

    union_set = litvar_set | clinvar_set
    intersection_set = litvar_set & clinvar_set
    new_pmid_set = union_set - baseline_set
    new_pmids = sorted(new_pmid_set, key=int)

    source_membership: dict[str, list[str]] = {}
    for pmid in new_pmids:
        sources = []
        if pmid in litvar_set:
            sources.append("litvar2")
        if pmid in clinvar_set:
            sources.append("clinvar")
        source_membership[pmid] = sources

    return {
        "litvar2_pmids": len(litvar_set),
        "clinvar_pmids": len(clinvar_set),
        "intersection_pmids": len(intersection_set),
        "union_pmids": len(union_set),
        "new_pmids": new_pmids,
        "source_membership": source_membership,
    }


# ---------------------------------------------------------------------------
# PubMed EFetch XML
# ---------------------------------------------------------------------------


def parse_pubmed_articles_xml(xml_text: str, *, expected_pmids: list[str]) -> dict[str, Any]:
    """Parse an NCBI Entrez EFetch `PubmedArticleSet` XML document into
    `{"articles", "requested_but_missing_pmids"}`. PMID/PMCID/DOI are
    extracted ONLY from each `PubmedArticle`'s direct
    `PubmedData/ArticleIdList/ArticleId` children (falling back to
    `MedlineCitation/PMID` only for the PMID itself, when `PubmedData` is
    entirely absent) -- an `ELocationID` (which may carry an unrelated/
    preprint DOI) and a nested `ReferenceList/Reference/ArticleIdList`
    entry (a CITED work's identifiers, not this article's own) are both
    ignored. DOI is lower-cased. `publication_date`/
    `publication_date_precision` preserve whatever precision PubMed
    actually reports (day/month/year/`MedlineDate`), reusing
    `raptor.external.tsc2_sources.pubmed`'s hardened partial-date parsing.
    A duplicate PMID within the response, or a PMID present in the
    response but absent from `expected_pmids`, is a hard parse failure.
    A PMID present in `expected_pmids` but absent from the response is
    reported (never raised) via `requested_but_missing_pmids`."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise R611QLiteratureParseError(f"pubmed efetch payload is not valid xml: {exc}") from exc

    seen_pmids: set[str] = set()
    rows: list[dict[str, Any]] = []

    for pubmed_article in root.findall("./PubmedArticle"):
        citation = pubmed_article.find("MedlineCitation")
        if citation is None:
            raise R611QLiteratureParseError("pubmed article is missing a MedlineCitation")
        article = citation.find("Article")
        if article is None:
            raise R611QLiteratureParseError("pubmed MedlineCitation is missing an Article")

        pubmed_data = pubmed_article.find("PubmedData")
        article_id_list = pubmed_data.find("ArticleIdList") if pubmed_data is not None else None

        pmid: str | None = None
        pmcid: str | None = None
        doi: str | None = None
        if article_id_list is not None:
            for article_id in article_id_list.findall("ArticleId"):
                id_type = article_id.get("IdType")
                text = _element_text(article_id)
                if not text:
                    continue
                if id_type == "pubmed":
                    pmid = text
                elif id_type == "pmc":
                    pmcid = text
                elif id_type == "doi":
                    doi = text.lower()

        if pmid is None:
            pmid = _element_text(citation.find("PMID"))
        if not pmid:
            raise R611QLiteratureParseError(
                "pubmed article is missing a pmid in PubmedData/ArticleIdList and "
                "MedlineCitation/PMID"
            )

        if pmid in seen_pmids:
            raise R611QLiteratureParseError(f"duplicate pmid {pmid} in pubmed efetch response")
        seen_pmids.add(pmid)

        title = _element_text(article.find("ArticleTitle"))
        try:
            publication_date, precision, _raw = _format_publication_date(
                article.find("Journal/JournalIssue/PubDate"), pmid=pmid
            )
        except _PubMedParseError as exc:
            raise R611QLiteratureParseError(
                f"pubmed article {pmid} has a malformed publication date: {exc}"
            ) from exc
        abstract = _extract_abstract(article)

        rows.append(
            {
                "pmid": pmid,
                "pmcid": pmcid,
                "doi": doi,
                "title": title,
                "publication_date": publication_date,
                "publication_date_precision": precision,
                "abstract": abstract,
            }
        )

    expected_pmid_set = set(expected_pmids)
    extra_pmids = sorted(seen_pmids - expected_pmid_set, key=int)
    if extra_pmids:
        raise R611QLiteratureParseError(
            f"pubmed efetch response contains extra pmid(s) not requested: {extra_pmids}"
        )

    requested_but_missing_pmids = sorted(expected_pmid_set - seen_pmids, key=int)

    return {"articles": rows, "requested_but_missing_pmids": requested_but_missing_pmids}


# ---------------------------------------------------------------------------
# Europe PMC "core"
# ---------------------------------------------------------------------------


_EUROPE_PMC_REQUIRED_SOURCE = "MED"


def _normalize_europe_pmc_licence(raw_licence: Any, *, pmid: str) -> str | None:
    """Normalize one Europe PMC "core" `license` value: `None` stays
    `None`; a string is trimmed of surrounding whitespace and
    case-folded to uppercase, then must match one of the KNOWN canonical
    licence values EXACTLY (`_KNOWN_EUROPE_PMC_LICENCES`) -- a near-match
    (missing the space between `CC`/`BY`, a hyphen swapped for a space, a
    trailing version suffix, etc.) is rejected rather than fuzzy-matched.
    A non-string, non-`None` value is rejected outright."""
    if raw_licence is None:
        return None
    if not isinstance(raw_licence, str):
        raise R611QLiteratureParseError(
            f"europe pmc core result {pmid} has a malformed licence type (expected a string "
            f"or null): {raw_licence!r} ({type(raw_licence).__name__})"
        )
    normalized = raw_licence.strip().upper()
    if normalized not in _KNOWN_EUROPE_PMC_LICENCES:
        raise R611QLiteratureParseError(
            f"europe pmc core result {pmid} has an unrecognized licence/license value: "
            f"{raw_licence!r}"
        )
    return normalized


def parse_europe_pmc_core(payload: str, *, requested_pmids: list[str]) -> dict[str, Any]:
    """Parse an Europe PMC `search?resultType=core` JSON response into
    `{"records", "requested_but_unresolved_pmids", "counts"}`. Only the
    requested PMID subset is ever accepted -- a returned record whose
    `pmid` is not in `requested_pmids` is a hard parse failure, as is any
    duplicate `pmid`. `hitCount` must be a genuine (never string-typed)
    non-negative integer that is at least the number of returned results
    (a total below what was actually returned is an internal
    inconsistency, never silently accepted). Every result's `source` must
    be exactly `"MED"` (this package never crosswalks a non-MEDLINE Europe
    PMC record), and when a result also carries its own `id` field it must
    equal that result's `pmid` exactly -- a drifting `id`/`pmid` pair is
    rejected rather than trusted on either side alone. `isOpenAccess` must
    be exactly `"Y"`/`"N"`; `license` must be `None` or a string that
    normalizes (via `_normalize_europe_pmc_licence`: trim + uppercase) to
    one of `_KNOWN_EUROPE_PMC_LICENCES` -- Europe PMC's real "core"
    responses emit lower-case, occasionally whitespace-padded licence
    strings (e.g. `"cc by-nc-nd"`), which are normalized to their
    canonical uppercase form; a non-string value or a near-match that
    still doesn't equal a known licence after normalization is rejected.
    `title`/`abstractText` must each be
    `None` or a string. `doi` must be `None` or an already-lower-cased,
    valid DOI (an upper/mixed-case DOI is rejected rather than silently
    re-normalized -- Europe PMC is expected to already emit the lower-cased
    form this pipeline standardizes on). A requested PMID absent from the
    response is reported (never raised) via `requested_but_unresolved_
    pmids`."""
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise R611QLiteratureParseError(f"europe pmc core payload is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise R611QLiteratureParseError(
            f"europe pmc core payload does not decode to a mapping: {type(document).__name__}"
        )
    result_list = document.get("resultList")
    if not isinstance(result_list, dict) or not isinstance(result_list.get("result"), list):
        raise R611QLiteratureParseError(
            f"europe pmc core payload is missing a resultList.result array: {result_list!r}"
        )
    raw_results = result_list["result"]

    hit_count = document.get("hitCount")
    if not isinstance(hit_count, int) or isinstance(hit_count, bool) or hit_count < 0:
        raise R611QLiteratureParseError(
            f"europe pmc core payload has a malformed hitcount (expected a non-negative "
            f"integer, never a string): {hit_count!r}"
        )
    if hit_count < len(raw_results):
        raise R611QLiteratureParseError(
            f"europe pmc core payload hitcount {hit_count!r} is inconsistent with the "
            f"{len(raw_results)!r} result(s) actually returned"
        )

    requested_pmid_set = set(requested_pmids)
    seen_pmids: set[str] = set()
    records: list[dict[str, Any]] = []
    pmcid_count = 0
    abstract_count = 0

    for entry in raw_results:
        if not isinstance(entry, dict):
            raise R611QLiteratureParseError(f"europe pmc core result entry is malformed: {entry!r}")
        pmid = entry.get("pmid")
        if not isinstance(pmid, str) or not _PMID_PATTERN.match(pmid):
            raise R611QLiteratureParseError(f"europe pmc core result has a malformed pmid: {pmid!r}")
        if pmid not in requested_pmid_set:
            raise R611QLiteratureParseError(
                f"europe pmc core result contains pmid {pmid!r} outside the requested subset "
                f"{sorted(requested_pmid_set, key=int)!r}"
            )
        if pmid in seen_pmids:
            raise R611QLiteratureParseError(f"duplicate pmid {pmid} in europe pmc core response")
        seen_pmids.add(pmid)

        source = entry.get("source")
        if source != _EUROPE_PMC_REQUIRED_SOURCE:
            raise R611QLiteratureParseError(
                f"europe pmc core result {pmid} has source {source!r}, expected exactly "
                f"{_EUROPE_PMC_REQUIRED_SOURCE!r}"
            )

        if "id" in entry and entry["id"] is not None and str(entry["id"]) != pmid:
            raise R611QLiteratureParseError(
                f"europe pmc core result id {entry['id']!r} does not equal its own pmid "
                f"{pmid!r}"
            )

        is_open_access = entry.get("isOpenAccess")
        if is_open_access not in _KNOWN_OPEN_ACCESS_VALUES:
            raise R611QLiteratureParseError(
                f"europe pmc core result {pmid} has an unrecognized open access value "
                f"(expected 'Y' or 'N'): {is_open_access!r}"
            )

        licence = _normalize_europe_pmc_licence(entry.get("license"), pmid=pmid)

        pmcid = entry.get("pmcid")
        if pmcid is not None:
            if not isinstance(pmcid, str) or not _PMCID_PATTERN.match(pmcid):
                raise R611QLiteratureParseError(
                    f"europe pmc core result {pmid} has a malformed pmcid: {pmcid!r}"
                )
            pmcid_count += 1

        raw_doi = entry.get("doi")
        if raw_doi is not None:
            if not isinstance(raw_doi, str) or not _DOI_PATTERN.match(raw_doi):
                raise R611QLiteratureParseError(
                    f"europe pmc core result {pmid} has a malformed doi: {raw_doi!r}"
                )
            if raw_doi != raw_doi.lower():
                raise R611QLiteratureParseError(
                    f"europe pmc core result {pmid} has a non-lower-cased doi (expected an "
                    f"already-normalized lower-case value): {raw_doi!r}"
                )
        doi = raw_doi

        title = entry.get("title")
        if title is not None and not isinstance(title, str):
            raise R611QLiteratureParseError(
                f"europe pmc core result {pmid} has a malformed title (expected a string or "
                f"null): {title!r} ({type(title).__name__})"
            )

        abstract = entry.get("abstractText")
        if abstract is not None:
            if not isinstance(abstract, str):
                raise R611QLiteratureParseError(
                    f"europe pmc core result {pmid} has a malformed abstractText (expected a "
                    f"string or null): {abstract!r} ({type(abstract).__name__})"
                )
            abstract_count += 1

        records.append(
            {
                "pmid": pmid,
                "pmcid": pmcid,
                "doi": doi,
                "title": title,
                "abstract": abstract,
                "is_open_access": is_open_access,
                "licence": licence,
            }
        )

    records.sort(key=lambda row: int(row["pmid"]))
    requested_but_unresolved_pmids = sorted(requested_pmid_set - seen_pmids, key=int)

    return {
        "records": records,
        "requested_but_unresolved_pmids": requested_but_unresolved_pmids,
        "counts": {
            "records_returned": len(records),
            "pmcid_count": pmcid_count,
            "abstract_count": abstract_count,
        },
    }


# ---------------------------------------------------------------------------
# CC BY full-text selection + JATS parsing
# ---------------------------------------------------------------------------


def select_cc_by_fulltext_candidates(records: list[dict[str, Any]]) -> list[str]:
    """Return the PMCIDs (in input order) of every Europe PMC "core" record
    that is eligible for full-text acquisition: a well-formed PMCID
    (`PMC<digits>`), `licence` exactly `"CC BY"`, and `is_open_access`
    exactly `"Y"`. A record with a malformed/missing PMCID, or any other
    licence/open-access value, is silently excluded (this is a selection
    filter, not a validator)."""
    candidates: list[str] = []
    for record in records:
        pmcid = record.get("pmcid")
        if not isinstance(pmcid, str) or not _PMCID_PATTERN.match(pmcid):
            continue
        if record.get("licence") != "CC BY":
            continue
        if record.get("is_open_access") != "Y":
            continue
        candidates.append(pmcid)
    return candidates


def _detect_restricted_cc_modifier(licence_text: str) -> str | None:
    """Return the restricted Creative Commons modifier (`"NC"`/`"ND"`/
    `"SA"`) detected in `licence_text`, or `None` if no restriction
    indicator (abbreviation, full word, or URL slug) is present."""
    abbrev_match = _RESTRICTED_CC_ABBREV_PATTERN.search(licence_text)
    if abbrev_match:
        return abbrev_match.group(1).upper()
    for pattern, modifier in _RESTRICTED_CC_WORD_PATTERNS:
        if pattern.search(licence_text):
            return modifier
    return None


def parse_cc_by_jats_fulltext(xml_text: str, *, expected_pmcid: str) -> dict[str, Any]:
    """Parse a JATS full-text XML document and enforce that its
    `front/article-meta/permissions/license/license-p` paragraph
    EXPLICITLY declares an unrestricted CC BY licence: any `NC`/`ND`/`SA`
    modifier -- whether abbreviated (`CC BY-NC`, `CC BY-ND`, `CC BY-SA`,
    `CC BY-NC-ND`), spelled out in full words (`Attribution-NonCommercial`,
    `Attribution-NoDerivatives`, `Attribution-ShareAlike`), or embedded in
    a restricted licence URL slug (`/licenses/by-nc/`, `/by-nd/`,
    `/by-sa/`) -- is rejected, and a missing licence paragraph is rejected
    -- an open-access-looking `license-type="open-access"` attribute is
    never treated as a substitute for an explicit declaration. Also
    enforces the document's own `pmcid` article-id equals `expected_
    pmcid`. Reuses `raptor.external.tsc2_sources.pmc`'s hardened PMCID/
    licence-paragraph extraction. The raw XML bytes are hashed exactly as
    received."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise JatsIdentityError(f"jats fulltext payload is not valid xml: {exc}") from exc

    article_meta = root.find("./front/article-meta")
    if article_meta is None:
        raise JatsIdentityError("jats document is missing front/article-meta")

    try:
        pmcid = _extract_pmcid(article_meta)
    except _PmcParseError as exc:  # pragma: no cover - defensive, _extract_pmcid never raises
        raise JatsIdentityError(str(exc)) from exc
    if pmcid is None:
        raise JatsIdentityError(
            "jats document is missing an article-id[pub-id-type='pmcid']"
        )
    if pmcid != expected_pmcid:
        raise JatsIdentityError(
            f"jats pmcid {pmcid!r} does not match expected pmcid {expected_pmcid!r}"
        )

    licence_text = _extract_license_text(article_meta)
    if not licence_text:
        raise JatsLicenceRejectedError(
            "jats license declaration is missing an explicit license-p licence paragraph; "
            "only an explicit attribution-only license is accepted"
        )

    modifier = _detect_restricted_cc_modifier(licence_text)
    if modifier is not None:
        raise JatsLicenceRejectedError(
            f"jats license text declares a restricted Creative Commons variant (modifier "
            f"{modifier}) in {licence_text!r}; only an unrestricted CC BY license is "
            f"accepted, not CC BY-{modifier}"
        )
    if not any(pattern.search(licence_text) for pattern in _POSITIVE_CC_BY_PATTERNS):
        raise JatsLicenceRejectedError(
            f"jats license text does not explicitly declare an unrestricted CC BY license: "
            f"{licence_text!r}"
        )

    return {
        "pmcid": pmcid,
        "licence_text": licence_text,
        "licence": "CC BY",
        "raw_xml_sha256": hashlib.sha256(xml_text.encode("utf-8")).hexdigest(),
    }


# ---------------------------------------------------------------------------
# Article index
# ---------------------------------------------------------------------------


def _validate_source_membership(new_pmids: list[str], source_membership: dict[str, list[str]]) -> None:
    new_pmid_set = set(new_pmids)
    membership_keys = set(source_membership)
    if membership_keys != new_pmid_set:
        missing = sorted(new_pmid_set - membership_keys, key=int)
        extra = sorted(membership_keys - new_pmid_set, key=int)
        raise R611QLiteratureParseError(
            "source_membership must be an ordered subset covering exactly new_pmids "
            f"(no missing/extra PMID coverage): missing={missing!r} extra={extra!r}"
        )
    for pmid, sources in source_membership.items():
        if not isinstance(sources, list) or not sources:
            raise R611QLiteratureParseError(
                f"source_membership for pmid {pmid} must be a non-empty ordered subset: "
                f"{sources!r}"
            )
        if len(sources) != len(set(sources)):
            raise R611QLiteratureParseError(
                f"source_membership for pmid {pmid} has duplicate source entries: {sources!r}"
            )
        unknown = [s for s in sources if s not in DISCOVERY_SOURCE_ORDER]
        if unknown:
            raise R611QLiteratureParseError(
                f"source_membership for pmid {pmid} has unknown source(s) {unknown!r} "
                f"(expected a subset of {DISCOVERY_SOURCE_ORDER!r}): {sources!r}"
            )
        canonical_order = [s for s in DISCOVERY_SOURCE_ORDER if s in sources]
        if list(sources) != canonical_order:
            raise R611QLiteratureParseError(
                f"source_membership for pmid {pmid} is not ordered per "
                f"{DISCOVERY_SOURCE_ORDER!r}: {sources!r}"
            )


def _reconcile_identity(pubmed_value: Any, europe_pmc_value: Any, *, field_name: str, pmid: str) -> Any:
    if pubmed_value is None:
        return europe_pmc_value
    if europe_pmc_value is None:
        return pubmed_value
    if pubmed_value != europe_pmc_value:
        raise R611QLiteratureParseError(
            f"pmid {pmid} has a {field_name} identity conflict between pubmed "
            f"({pubmed_value!r}) and europe_pmc ({europe_pmc_value!r})"
        )
    return pubmed_value


ALLOWED_FULLTEXT_ENTRY_STATUSES = frozenset({"ACQUIRED_CC_BY", "JATS_LICENCE_REJECTED"})
_FULLTEXT_ENTRY_FIELDS = frozenset({"fulltext_status", "artifact_id"})


def _validate_fulltext_status_entry(pmcid: str, entry: Any) -> None:
    if not isinstance(entry, dict) or set(entry) != _FULLTEXT_ENTRY_FIELDS:
        raise R611QLiteratureParseError(
            f"fulltext_status_by_pmcid entry for pmcid {pmcid!r} must have exactly "
            f"{sorted(_FULLTEXT_ENTRY_FIELDS)!r} fields: {entry!r}"
        )
    status = entry["fulltext_status"]
    artifact_id = entry["artifact_id"]
    if status not in ALLOWED_FULLTEXT_ENTRY_STATUSES:
        raise R611QLiteratureParseError(
            f"fulltext_status_by_pmcid entry for pmcid {pmcid!r} has an unknown fulltext "
            f"status {status!r} (expected one of {sorted(ALLOWED_FULLTEXT_ENTRY_STATUSES)!r})"
        )
    if status == "ACQUIRED_CC_BY":
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            raise R611QLiteratureParseError(
                f"fulltext_status_by_pmcid entry for pmcid {pmcid!r} with status "
                f"ACQUIRED_CC_BY must carry a non-null artifact_id: {entry!r}"
            )
    elif artifact_id is not None:
        raise R611QLiteratureParseError(
            f"fulltext_status_by_pmcid entry for pmcid {pmcid!r} with status {status!r} must "
            f"carry a null artifact_id: {entry!r}"
        )


def _assert_fulltext_status_consistency(pmid: str, fulltext_status: Any, fulltext_artifact_id: Any) -> None:
    if fulltext_status == "ACQUIRED_CC_BY":
        if not isinstance(fulltext_artifact_id, str) or not fulltext_artifact_id.strip():
            raise R611QLiteratureParseError(
                f"article index row {pmid!r} has fulltext_status ACQUIRED_CC_BY but a null/"
                f"empty fulltext_artifact_id: {fulltext_artifact_id!r}"
            )
    elif fulltext_artifact_id is not None:
        raise R611QLiteratureParseError(
            f"article index row {pmid!r} has fulltext_status {fulltext_status!r} but a "
            f"non-null fulltext_artifact_id: {fulltext_artifact_id!r}"
        )


def build_article_index_records(
    *,
    new_pmids: list[str],
    source_membership: dict[str, list[str]],
    pubmed_articles: list[dict[str, Any]],
    europe_pmc_records: list[dict[str, Any]],
    fulltext_status_by_pmcid: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build one `raptor.external.r611q_literature_article.v1` row per new
    PMID lead, sorted numerically. `new_pmids` itself, `pubmed_articles`
    and `europe_pmc_records` must each carry no duplicate `pmid` -- a
    duplicate anywhere is a hard failure, never silently deduplicated or
    overwritten. Cross-references PubMed and Europe PMC identity (PMCID/
    DOI) for the same PMID and rejects any conflict rather than silently
    preferring one side (a value present on only one side is used as-is --
    the "null-side identity fallback"). A PMID unresolved by PubMed/Europe
    PMC gets an explicit non-`RESOLVED` status with null bibliographic
    fields rather than being dropped. `fulltext_status_by_pmcid` may only
    reference a PMCID that is actually the reconciled identity of one of
    these rows (an unknown PMCID is rejected), and each entry's shape/
    status/artifact_id pairing is validated (`ACQUIRED_CC_BY` <->
    non-null `artifact_id`; any other allowed status <-> null
    `artifact_id`; an unrecognized status is rejected). No evidence claim,
    pathogenicity assertion or classification is ever added."""
    if len(new_pmids) != len(set(new_pmids)):
        seen: set[str] = set()
        duplicates = sorted({pmid for pmid in new_pmids if pmid in seen or seen.add(pmid)}, key=int)
        raise R611QLiteratureParseError(f"new_pmids contains duplicate pmid(s): {duplicates!r}")

    _validate_source_membership(new_pmids, source_membership)

    pubmed_by_pmid: dict[str, dict[str, Any]] = {}
    for row in pubmed_articles:
        pmid = row["pmid"]
        if pmid in pubmed_by_pmid:
            raise R611QLiteratureParseError(f"duplicate pubmed article record for pmid {pmid!r}")
        pubmed_by_pmid[pmid] = row

    europe_pmc_by_pmid: dict[str, dict[str, Any]] = {}
    for row in europe_pmc_records:
        pmid = row["pmid"]
        if pmid in europe_pmc_by_pmid:
            raise R611QLiteratureParseError(f"duplicate europe_pmc record for pmid {pmid!r}")
        europe_pmc_by_pmid[pmid] = row

    partial_rows: list[dict[str, Any]] = []
    known_pmcids: set[str] = set()
    for pmid in sorted(new_pmids, key=int):
        pubmed_row = pubmed_by_pmid.get(pmid)
        europe_pmc_row = europe_pmc_by_pmid.get(pmid)

        if pubmed_row is not None:
            pubmed_status = "RESOLVED"
            title = pubmed_row.get("title")
            publication_date = pubmed_row.get("publication_date")
            publication_date_precision = pubmed_row.get("publication_date_precision")
            abstract = pubmed_row.get("abstract")
            pubmed_pmcid = pubmed_row.get("pmcid")
            pubmed_doi = _normalize_doi(pubmed_row.get("doi"))
        else:
            pubmed_status = "PUBMED_UNRESOLVED"
            title = None
            publication_date = None
            publication_date_precision = None
            abstract = None
            pubmed_pmcid = None
            pubmed_doi = None

        if europe_pmc_row is not None:
            europe_pmc_status = "RESOLVED"
            is_open_access = europe_pmc_row.get("is_open_access")
            licence = europe_pmc_row.get("licence")
            europe_pmc_pmcid = europe_pmc_row.get("pmcid")
            europe_pmc_doi = _normalize_doi(europe_pmc_row.get("doi"))
        else:
            europe_pmc_status = "EUROPE_PMC_UNRESOLVED"
            is_open_access = None
            licence = None
            europe_pmc_pmcid = None
            europe_pmc_doi = None

        pmcid = _reconcile_identity(pubmed_pmcid, europe_pmc_pmcid, field_name="pmcid", pmid=pmid)
        doi = _reconcile_identity(pubmed_doi, europe_pmc_doi, field_name="doi", pmid=pmid)
        if pmcid:
            known_pmcids.add(pmcid)

        partial_rows.append(
            {
                "schema": ARTICLE_INDEX_SCHEMA,
                "pmid": pmid,
                "discovery_sources": list(source_membership[pmid]),
                "pubmed_status": pubmed_status,
                "pmcid": pmcid,
                "doi": doi,
                "title": title,
                "publication_date": publication_date,
                "publication_date_precision": publication_date_precision,
                "abstract": abstract,
                "europe_pmc_status": europe_pmc_status,
                "is_open_access": is_open_access,
                "licence": licence,
            }
        )

    unknown_pmcids = sorted(set(fulltext_status_by_pmcid) - known_pmcids)
    if unknown_pmcids:
        raise R611QLiteratureParseError(
            f"fulltext_status_by_pmcid references pmcid(s) that are not the reconciled "
            f"identity of any article-index row: {unknown_pmcids!r}"
        )
    for pmcid, entry in fulltext_status_by_pmcid.items():
        _validate_fulltext_status_entry(pmcid, entry)

    rows: list[dict[str, Any]] = []
    for row in partial_rows:
        pmcid = row["pmcid"]
        fulltext_entry = fulltext_status_by_pmcid.get(pmcid) if pmcid else None
        if fulltext_entry is not None:
            fulltext_status = fulltext_entry["fulltext_status"]
            fulltext_artifact_id = fulltext_entry["artifact_id"]
        else:
            fulltext_status = "NOT_ELIGIBLE"
            fulltext_artifact_id = None
        _assert_fulltext_status_consistency(row["pmid"], fulltext_status, fulltext_artifact_id)
        row["fulltext_status"] = fulltext_status
        row["fulltext_artifact_id"] = fulltext_artifact_id
        rows.append(row)

    return rows


def to_article_index_jsonl(rows: list[dict[str, Any]]) -> str:
    """Serialize article-index rows to a deterministic JSONL string: rows
    are sorted numerically by `pmid` regardless of input order, and each
    line is canonical JSON (sorted keys, compact separators). Every row is
    revalidated before serialization -- exactly the 15
    `ARTICLE_INDEX_FIELDS`, a unique `pmid` across all rows, and
    `fulltext_status`/`fulltext_artifact_id` consistency (`ACQUIRED_CC_BY`
    <-> non-null `artifact_id`; anything else <-> null `artifact_id`) --
    so a caller can never accidentally serialize a malformed/mutated row."""
    seen_pmids: set[str] = set()
    for row in rows:
        row_fields = set(row)
        if row_fields != ARTICLE_INDEX_FIELDS:
            missing = ARTICLE_INDEX_FIELDS - row_fields
            extra = row_fields - ARTICLE_INDEX_FIELDS
            raise R611QLiteratureParseError(
                f"article index row does not have the exact required fields: "
                f"missing={sorted(missing)!r} extra={sorted(extra)!r}"
            )
        pmid = row["pmid"]
        if pmid in seen_pmids:
            raise R611QLiteratureParseError(f"article index has a duplicate pmid row: {pmid!r}")
        seen_pmids.add(pmid)
        _assert_fulltext_status_consistency(pmid, row["fulltext_status"], row["fulltext_artifact_id"])

    sorted_rows = sorted(rows, key=lambda row: int(row["pmid"]))
    lines = [_canonical_json(row) for row in sorted_rows]
    return "".join(line + "\n" for line in lines)


__all__ = [
    "R611QLiteratureParseError",
    "JatsIdentityError",
    "JatsLicenceRejectedError",
    "ARTICLE_INDEX_SCHEMA",
    "ARTICLE_INDEX_FIELDS",
    "DISCOVERY_SOURCE_ORDER",
    "ALLOWED_FULLTEXT_ENTRY_STATUSES",
    "parse_baseline_manifest",
    "parse_litvar_publications",
    "parse_clinvar_uid_esearch",
    "parse_clinvar_pubmed_links",
    "derive_discovery_membership",
    "parse_pubmed_articles_xml",
    "parse_europe_pmc_core",
    "select_cc_by_fulltext_candidates",
    "parse_cc_by_jats_fulltext",
    "build_article_index_records",
    "to_article_index_jsonl",
]
