"""Independent score-set metadata observation for `verify_registered_source`.

`raptor.external.mave.register.verify_registered_source` is only a real check
when `observed_transcript`/`observed_license` are extracted from data that is
genuinely independent of the `SourceRegisterEntry` under test -- never the
same `entry.transcript`/`entry.license` fields being verified. This module
parses the MaveDB score-set metadata API response (the `api.score_set` URL
already registered per-source in `configs/external/mave_sources.yaml`, e.g.
`https://api.mavedb.org/api/v1/score-sets/urn:mavedb:00001201-a-1`) -- a
document that is fetched/cached separately from the pinned register entry --
and derives the observed transcript (from the response's free-text
`methodText`, e.g. "Variants based on Refseq transcript NM_000548.5.") and
license (from the response's structured `license` object, e.g.
`{"shortName": "CC0", "version": "1.0"}` -> `"CC0-1.0"`).

Neither value is read off the `SourceRegisterEntry` itself: a call site that
still passes `entry.transcript`/`entry.license` straight through is exactly
the tautological self-comparison this module exists to eliminate.
"""
from __future__ import annotations

import json
import re
from typing import Callable

_TRANSCRIPT_RE = re.compile(r"\bN[MR]_\d+\.\d+\b")


class ScoreSetMetadataError(ValueError):
    """Raised when a fetched score-set metadata document cannot be parsed, or
    does not carry a transcript/license value this module knows how to
    extract -- never silently defaulted or guessed."""


def parse_score_set_metadata(raw_text: str) -> dict:
    """Parse the MaveDB score-set metadata JSON response body. Raises
    `ScoreSetMetadataError` (never a bare `json.JSONDecodeError`) on
    malformed input so call sites get a single, MAVE-specific error type."""
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ScoreSetMetadataError(f"score-set metadata is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ScoreSetMetadataError(
            f"score-set metadata must be a JSON object; got {type(payload).__name__}"
        )
    return payload


def extract_observed_transcript(metadata: dict) -> str:
    """Extract the target RefSeq transcript accession from the free-text
    `methodText` field of a MaveDB score-set metadata response (the only
    place this particular score-set states its target transcript). Raises
    if zero or more-than-one distinct accession is found -- never guesses
    which one is authoritative."""
    method_text = metadata.get("methodText") or ""
    matches = sorted(set(_TRANSCRIPT_RE.findall(method_text)))
    if not matches:
        raise ScoreSetMetadataError(
            "no RefSeq transcript accession (NM_/NR_###.#) found in score-set "
            "metadata's methodText -- refusing to guess the observed transcript"
        )
    if len(matches) > 1:
        raise ScoreSetMetadataError(
            f"methodText names more than one distinct transcript accession {matches!r} -- "
            "refusing to pick one as the observed transcript"
        )
    return matches[0]


def extract_observed_license(metadata: dict) -> str:
    """Extract the license identifier (e.g. `CC0-1.0`) from a MaveDB
    score-set metadata response's structured `license` object
    (`{"shortName": "CC0", "version": "1.0", ...}`). Raises if the license
    object or its required fields are missing -- never defaults to the
    register's own pinned license value."""
    license_obj = metadata.get("license")
    if not isinstance(license_obj, dict):
        raise ScoreSetMetadataError(
            "score-set metadata has no structured 'license' object -- refusing to guess "
            "the observed license"
        )
    short_name = license_obj.get("shortName")
    version = license_obj.get("version")
    if not short_name or not version:
        raise ScoreSetMetadataError(
            f"score-set metadata license object is missing shortName/version: {license_obj!r}"
        )
    return f"{short_name}-{version}"


def observe_transcript_and_license(metadata: dict) -> tuple[str, str]:
    """Convenience wrapper: `(observed_transcript, observed_license)` from an
    already-parsed score-set metadata document."""
    return extract_observed_transcript(metadata), extract_observed_license(metadata)


def fetch_score_set_metadata(url: str, *, fetcher: Callable[[str], str]) -> dict:
    """Fetch (via an injected `fetcher`, never a real network call performed
    implicitly -- mirrors `source.load_score_records`'s local-seam pattern)
    and parse the MaveDB score-set metadata document at `url`."""
    raw_text = fetcher(url)
    return parse_score_set_metadata(raw_text)


__all__ = [
    "ScoreSetMetadataError",
    "parse_score_set_metadata",
    "extract_observed_transcript",
    "extract_observed_license",
    "observe_transcript_and_license",
    "fetch_score_set_metadata",
]
