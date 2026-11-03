"""NCBI Entrez ESearch/EFetch response parsing for the PubMed literature
source.

`parse_esearch_payload` parses the *actual* ESearch JSON response shape --
which does not echo a `db` field back (unlike some historical/other Entrez
responses) -- and fails loud on a malformed top level, a malformed
`esearchresult` shape, a non-numeric `count`, or a missing required PMID.
`required_pmid_present` is always `True` in a returned record: a missing
required PMID is a hard failure, never a soft `False` a caller could ignore.

`parse_efetch_xml` extracts PMID/DOI/title/publication-date/abstract text
from the EFetch XML metadata response *verbatim* -- it performs no evidence
inference (e.g. it never inspects title/abstract wording for terms like
"pathogenic"/"benign"; those words are preserved as opaque source text).

A PubMed `PubDate` is never assumed to carry a full Year/Month/Day: a
`Year`-only or `Year`+`Month`-only `PubDate`, or a `MedlineDate` fallback
string (used when NLM cannot structure the date at all, e.g. `"2026
Winter"`), are all valid and are never rejected nor filled in with an
invented day/month. `publication_date` always preserves the highest
precision actually present -- `YYYY`, `YYYY-MM`, `YYYY-MM-DD`, or the raw
`MedlineDate` text -- and a row whose precision is anything other than a
full day (`YYYY-MM-DD`) additionally carries `publication_date_precision`
and `publication_date_raw` so a caller can tell a partial/MedlineDate
result apart from a fully-dated one without any additional parsing. A row
with full day precision carries only the original five fields
(`pmid`/`doi`/`title`/`publication_date`/`abstract`) for backward
compatibility with the exact-day case.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any

_MONTH_NAME_TO_NUMBER = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


class PubMedParseError(ValueError):
    """Raised when a PubMed ESearch/EFetch response cannot be parsed, or
    fails a required structural/content validation."""


def parse_esearch_payload(
    payload: str,
    *,
    expected_db: str,
    required_pmid: str,
) -> dict[str, Any]:
    """Parse an NCBI Entrez ESearch JSON response body into
    `{"count", "pmids", "returned_count", "is_truncated",
    "required_pmid_present"}`. Raises `PubMedParseError` if the top-level
    `esearchresult` key is missing, its value is not a JSON object, `count`
    is not numeric, `idlist` is missing/malformed, or `required_pmid` is not
    present among the returned PMIDs."""
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise PubMedParseError(f"esearch payload is not valid JSON: {exc}") from exc

    if not isinstance(document, dict) or "esearchresult" not in document:
        raise PubMedParseError(
            "esearch payload is missing the required top-level 'esearchresult' key"
        )

    result = document["esearchresult"]
    if not isinstance(result, dict):
        raise PubMedParseError(
            "esearchresult value has a malformed shape: expected a JSON object, "
            f"got {type(result).__name__}"
        )

    # The real ESearch response does not echo a `db` field; only validate it
    # if a (non-standard) response happens to include one.
    if "db" in result and result["db"] != expected_db:
        raise PubMedParseError(
            f"esearchresult db {result['db']!r} does not match expected database "
            f"{expected_db!r}"
        )

    if "count" not in result:
        raise PubMedParseError("esearchresult is missing the required 'count' field")
    try:
        count = int(result["count"])
    except (TypeError, ValueError) as exc:
        raise PubMedParseError(
            f"esearchresult count is malformed (not an integer): {result['count']!r}"
        ) from exc

    idlist = result.get("idlist")
    if not isinstance(idlist, list) or not all(isinstance(pmid, str) for pmid in idlist):
        raise PubMedParseError(
            f"esearchresult idlist is missing or malformed: {idlist!r}"
        )

    returned_count = len(idlist)
    is_truncated = returned_count < count

    if required_pmid not in idlist:
        raise PubMedParseError(
            f"required PMID {required_pmid} is not present in the esearch idlist"
        )

    return {
        "count": count,
        "pmids": list(idlist),
        "returned_count": returned_count,
        "is_truncated": is_truncated,
        "required_pmid_present": True,
    }


def _element_text(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    # Preserve all textual content -- including any nested formatting
    # elements' text -- in document order via itertext(); the only
    # normalization applied is joining those fragments and stripping
    # surrounding whitespace.
    text = "".join(element.itertext()).strip()
    return text or None


def _format_publication_date(pub_date: ET.Element | None, *, pmid: str) -> tuple[str, str, str]:
    """Return `(publication_date, precision, raw)` for one PubMed `PubDate`
    element, preserving whatever precision is actually present:

    - `Year` + `Month` + `Day` -> `("YYYY-MM-DD", "day", "YYYY-MM-DD")`
    - `Year` + `Month` (no `Day`) -> `("YYYY-MM", "month", "YYYY-MM")`
    - `Year` only -> `("YYYY", "year", "YYYY")`
    - `MedlineDate` only (no structured `Year`) -> the raw MedlineDate text
      for all three, e.g. `("2026 Winter", "medline", "2026 Winter")`

    Never invents a missing day/month, and never rejects a partial date or
    a `MedlineDate` fallback as a parse failure."""
    if pub_date is None:
        raise PubMedParseError(f"PMID {pmid} is missing a Journal/JournalIssue/PubDate")

    year = _element_text(pub_date.find("Year"))
    month = _element_text(pub_date.find("Month"))
    day = _element_text(pub_date.find("Day"))

    if year and month and day:
        if month.isdigit():
            month_number = int(month)
        else:
            month_number = _MONTH_NAME_TO_NUMBER.get(month.strip().lower()[:3])
            if month_number is None:
                raise PubMedParseError(f"PMID {pmid} has an unrecognized PubDate Month: {month!r}")
        if not day.isdigit():
            raise PubMedParseError(f"PMID {pmid} has a non-numeric PubDate Day: {day!r}")
        formatted = f"{year}-{month_number:02d}-{int(day):02d}"
        return formatted, "day", formatted

    if year and month:
        if month.isdigit():
            month_number = int(month)
        else:
            month_number = _MONTH_NAME_TO_NUMBER.get(month.strip().lower()[:3])
            if month_number is None:
                raise PubMedParseError(f"PMID {pmid} has an unrecognized PubDate Month: {month!r}")
        formatted = f"{year}-{month_number:02d}"
        return formatted, "month", formatted

    if year:
        return year, "year", year

    medline_date = _element_text(pub_date.find("MedlineDate"))
    if medline_date:
        return medline_date, "medline", medline_date

    raise PubMedParseError(
        f"PMID {pmid} has a PubDate with no Year and no MedlineDate fallback"
    )


def _extract_doi(article: ET.Element) -> str | None:
    for eloc in article.findall("ELocationID"):
        if eloc.get("EIdType") == "doi" and eloc.text and eloc.text.strip():
            return eloc.text.strip()
    return None


def _extract_abstract(article: ET.Element) -> str | None:
    paragraphs = [
        "".join(node.itertext()).strip()
        for node in article.findall("Abstract/AbstractText")
    ]
    paragraphs = [text for text in paragraphs if text]
    return " ".join(paragraphs) if paragraphs else None


def parse_efetch_xml(
    xml_text: str,
    *,
    expected_pmids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Parse an NCBI Entrez EFetch `PubmedArticleSet` XML document into one
    record per `PubmedArticle`: `{"pmid", "doi", "title", "publication_date",
    "abstract"}` (partial-date rows additionally carry
    `publication_date_precision`/`publication_date_raw`; see the module
    docstring). Title and abstract text are copied verbatim -- no
    filtering, summarization or evidence inference is performed here. When
    `expected_pmids` is given (the caller's own ESearch PMID set), the
    returned PMIDs must equal it EXACTLY -- no missing and no extra
    records -- and any drift is a hard `PubMedParseError`, never a silently
    accepted partial/superset result."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise PubMedParseError(f"efetch payload is not valid XML: {exc}") from exc

    rows: list[dict[str, Any]] = []
    for pubmed_article in root.findall("./PubmedArticle"):
        citation = pubmed_article.find("MedlineCitation")
        if citation is None:
            raise PubMedParseError("PubmedArticle is missing a MedlineCitation")

        pmid_element = citation.find("PMID")
        pmid = _element_text(pmid_element)
        if not pmid:
            raise PubMedParseError("MedlineCitation is missing a PMID")

        article = citation.find("Article")
        if article is None:
            raise PubMedParseError(f"PMID {pmid} MedlineCitation is missing an Article")

        title = _element_text(article.find("ArticleTitle"))
        doi = _extract_doi(article)
        publication_date, precision, raw = _format_publication_date(
            article.find("Journal/JournalIssue/PubDate"), pmid=pmid
        )
        abstract = _extract_abstract(article)

        row: dict[str, Any] = {
            "pmid": pmid,
            "doi": doi,
            "title": title,
            "publication_date": publication_date,
            "abstract": abstract,
        }
        if precision != "day":
            row["publication_date_precision"] = precision
            row["publication_date_raw"] = raw
        rows.append(row)

    if expected_pmids is not None:
        observed_pmid_set = {row["pmid"] for row in rows}
        expected_pmid_set = set(expected_pmids)
        if observed_pmid_set != expected_pmid_set:
            missing = sorted(expected_pmid_set - observed_pmid_set)
            extra = sorted(observed_pmid_set - expected_pmid_set)
            raise PubMedParseError(
                "efetch PMID identity does not equal the requested esearch PMID set "
                f"(no silent missing/extra records allowed): missing={missing!r} "
                f"extra={extra!r}"
            )

    return rows


__all__ = [
    "PubMedParseError",
    "parse_esearch_payload",
    "parse_efetch_xml",
]
