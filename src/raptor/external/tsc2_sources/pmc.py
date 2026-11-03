"""PMC/Europe PMC JATS full-text and explicit-licence parsing.

`parse_fulltext_jats` extracts the article's PMCID and its explicit licence
declaration (the `front/article-meta/permissions/license/license-p` text)
from a JATS XML document. A missing licence declaration becomes
`LICENCE_REVIEW_REQUIRED` -- this module never infers an open licence from
a `license-type="open-access"` attribute, from the mere existence of a PMC
record, or from any other proxy signal; only actual declared licence text
counts as `EXPLICIT_LICENSE_DECLARED`. The raw XML bytes are hashed exactly
as received (never re-serialized) so the caller can pin/verify what was
actually fetched.
"""
from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from typing import Any


class PmcParseError(ValueError):
    """Raised when a PMC JATS full-text document cannot be parsed, is
    missing its PMCID, or does not match the expected PMCID."""


def _extract_pmcid(article_meta: ET.Element) -> str | None:
    for article_id in article_meta.findall("article-id"):
        if article_id.get("pub-id-type") == "pmcid" and article_id.text and article_id.text.strip():
            return article_id.text.strip()
    return None


def _extract_license_text(article_meta: ET.Element) -> str | None:
    permissions = article_meta.find("permissions")
    if permissions is None:
        return None
    paragraphs = [
        "".join(node.itertext()).strip()
        for node in permissions.findall("license/license-p")
    ]
    paragraphs = [text for text in paragraphs if text]
    return " ".join(paragraphs) if paragraphs else None


def parse_fulltext_jats(xml_text: str, *, expected_pmcid: str) -> dict[str, Any]:
    """Parse a JATS `<article>` full-text document into
    `{"pmcid", "license_text", "licence_state", "raw_xml_sha256"}`.
    `licence_state` is `EXPLICIT_LICENSE_DECLARED` only when an actual
    `license-p` paragraph is present; otherwise it is
    `LICENCE_REVIEW_REQUIRED` -- never assumed open. Raises `PmcParseError`
    if the document is not valid XML, has no `pmcid` article-id, or its
    `pmcid` does not match `expected_pmcid`."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise PmcParseError(f"PMC full-text payload is not valid XML: {exc}") from exc

    article_meta = root.find("./front/article-meta")
    if article_meta is None:
        raise PmcParseError("JATS document is missing front/article-meta")

    pmcid = _extract_pmcid(article_meta)
    if pmcid is None:
        raise PmcParseError(
            "JATS document is missing an article-id[pub-id-type='pmcid']"
        )
    if pmcid != expected_pmcid:
        raise PmcParseError(
            f"JATS pmcid {pmcid!r} does not match expected pmcid {expected_pmcid!r}"
        )

    license_text = _extract_license_text(article_meta)
    licence_state = (
        "EXPLICIT_LICENSE_DECLARED" if license_text else "LICENCE_REVIEW_REQUIRED"
    )

    return {
        "pmcid": pmcid,
        "license_text": license_text,
        "licence_state": licence_state,
        "raw_xml_sha256": hashlib.sha256(xml_text.encode("utf-8")).hexdigest(),
    }


__all__ = [
    "PmcParseError",
    "parse_fulltext_jats",
]
