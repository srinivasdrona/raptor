"""Pinned metadata policy for the ClinVar August 2026 prospective freeze.

The monthly archive object is fetched only through
``prospective_exact_source_transport``. NCBI publishes adjacent MD5 files for
the rolling ClinVar files, but its monthly ``tab_delimited/archive/`` index
does not publish checksums for archived copies. The earlier v2 registration
incorrectly assumed that ``<archive>.md5`` existed; the authorized v2 run
confirmed that the URL returns HTTP 404 before any archive body GET.

For the v3 registration this module provides two static, production-owned
lookups:

* ``published_archive_date_lookup`` returns the pinned release date and its
  reviewed authority.
* ``official_md5_lookup`` retains the historical port name for API
  compatibility, but returns the pinned fact that no upstream checksum is
  available and that content must be frozen using the exact URL, the
  preregistered HEAD continuity checks, and locally computed SHA-256 and MD5.

Neither lookup opens a socket. The live archive GET remains hard-wired to the
separate exact-source transport.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

__all__ = [
    "CONTENT_VERIFICATION_MODE",
    "MetadataLookupConfigurationError",
    "MetadataLookupError",
    "MetadataLookupPolicyError",
    "URL_POLICY_REASON",
    "official_md5_lookup",
    "published_archive_date_lookup",
]

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REGISTRATION_SPEC_PATH = (
    _REPO_ROOT / "docs" / "project" / "specs" / "clinvar-2026-08-prospective-amendment-v3.yaml"
)

URL_POLICY_REASON = "EXACT_REGISTERED_URL_REQUIRED"
CONTENT_VERIFICATION_MODE = "EXACT_URL_HEAD_CONTINUITY_PLUS_LOCAL_SHA256_MD5"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class MetadataLookupError(Exception):
    """Base class for metadata policy failures."""


class MetadataLookupConfigurationError(MetadataLookupError):
    """Raised when the pinned registration metadata is missing or malformed."""


class MetadataLookupPolicyError(MetadataLookupError):
    """Raised when a caller requests metadata for any unregistered URL."""

    def __init__(self, reason_code: str, reason: str) -> None:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("MetadataLookupPolicyError requires a non-blank reason")
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def _load_registered_metadata_pins() -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(_REGISTRATION_SPEC_PATH.read_text(encoding="utf-8"))
    except OSError as exc:
        raise MetadataLookupConfigurationError(f"unable to read registration spec: {exc}") from exc
    except yaml.YAMLError as exc:
        raise MetadataLookupConfigurationError(f"registration spec is not valid YAML: {exc}") from exc
    if not isinstance(loaded, dict):
        raise MetadataLookupConfigurationError("registration spec must parse to a mapping")

    dataset_registration = loaded.get("dataset_registration")
    if not isinstance(dataset_registration, dict):
        raise MetadataLookupConfigurationError("registration spec missing dataset_registration mapping")
    registered_url = dataset_registration.get("exact_url")
    if not isinstance(registered_url, str) or not registered_url:
        raise MetadataLookupConfigurationError("dataset_registration.exact_url must be a non-blank string")
    parsed_registered_url = urlsplit(registered_url)
    if (
        parsed_registered_url.scheme != "https"
        or parsed_registered_url.hostname != "ftp.ncbi.nlm.nih.gov"
        or parsed_registered_url.username is not None
        or parsed_registered_url.password is not None
        or parsed_registered_url.port is not None
        or parsed_registered_url.query
        or parsed_registered_url.fragment
    ):
        raise MetadataLookupConfigurationError(
            "dataset_registration.exact_url must be the pinned direct NCBI HTTPS URL "
            "without credentials, port, query, or fragment"
        )

    pins = dataset_registration.get("metadata_source_pins")
    if not isinstance(pins, dict):
        raise MetadataLookupConfigurationError(
            "registration spec missing dataset_registration.metadata_source_pins mapping"
        )

    published_archive_date = pins.get("published_archive_date")
    if not isinstance(published_archive_date, str) or not _DATE_RE.fullmatch(published_archive_date):
        raise MetadataLookupConfigurationError(
            "metadata_source_pins.published_archive_date must be an ISO YYYY-MM-DD date string"
        )
    try:
        date.fromisoformat(published_archive_date)
    except ValueError as exc:
        raise MetadataLookupConfigurationError(
            "metadata_source_pins.published_archive_date must be a real calendar date"
        ) from exc

    published_archive_date_authority = pins.get("published_archive_date_authority")
    if not isinstance(published_archive_date_authority, str) or not published_archive_date_authority.strip():
        raise MetadataLookupConfigurationError(
            "metadata_source_pins.published_archive_date_authority must be a non-blank string"
        )

    if pins.get("upstream_checksum_available") is not False:
        raise MetadataLookupConfigurationError(
            "metadata_source_pins.upstream_checksum_available must be false for this archive registration"
        )

    checksum_evidence_url = pins.get("upstream_checksum_evidence_url")
    expected_evidence_url = registered_url.rsplit("/", 1)[0] + "/"
    parsed_evidence_url = urlsplit(str(checksum_evidence_url))
    if (
        checksum_evidence_url != expected_evidence_url
        or parsed_evidence_url.scheme != "https"
        or parsed_evidence_url.hostname != parsed_registered_url.hostname
        or parsed_evidence_url.username is not None
        or parsed_evidence_url.password is not None
        or parsed_evidence_url.port is not None
        or parsed_evidence_url.query
        or parsed_evidence_url.fragment
    ):
        raise MetadataLookupConfigurationError(
            "metadata_source_pins.upstream_checksum_evidence_url must be the exact parent archive index URL"
        )

    unavailable_reason = pins.get("upstream_checksum_unavailable_reason")
    if not isinstance(unavailable_reason, str) or not unavailable_reason.strip():
        raise MetadataLookupConfigurationError(
            "metadata_source_pins.upstream_checksum_unavailable_reason must be a non-blank string"
        )

    verification_mode = pins.get("content_verification_mode")
    if verification_mode != CONTENT_VERIFICATION_MODE:
        raise MetadataLookupConfigurationError(
            "metadata_source_pins.content_verification_mode must equal "
            f"{CONTENT_VERIFICATION_MODE!r}"
        )

    return {
        "registered_url": registered_url,
        "published_archive_date": published_archive_date,
        "published_archive_date_authority": published_archive_date_authority,
        "upstream_checksum_available": False,
        "upstream_checksum_evidence_url": checksum_evidence_url,
        "upstream_checksum_unavailable_reason": unavailable_reason,
        "content_verification_mode": verification_mode,
    }


def _require_registered_url(url: str, pins: dict[str, Any]) -> None:
    if url != pins["registered_url"]:
        raise MetadataLookupPolicyError(
            URL_POLICY_REASON, f"url is not the exact registered archive URL: {url!r}"
        )


def published_archive_date_lookup(url: str) -> dict[str, Any]:
    pins = _load_registered_metadata_pins()
    _require_registered_url(url, pins)
    return {
        "published_archive_date": pins["published_archive_date"],
        "source_identity": pins["published_archive_date_authority"],
    }


def official_md5_lookup(url: str) -> dict[str, Any]:
    """Return the pinned absence of an upstream checksum.

    The name is retained because ``execute_transport_and_raw_freeze`` already
    exposes this internal port. ``official_md5`` is deliberately ``None`` and
    must never be presented as an NCBI-verified digest.
    """
    pins = _load_registered_metadata_pins()
    _require_registered_url(url, pins)
    return {
        "official_md5": None,
        "upstream_checksum_available": False,
        "source_identity": pins["upstream_checksum_evidence_url"],
        "unavailable_reason": pins["upstream_checksum_unavailable_reason"],
        "verification_mode": pins["content_verification_mode"],
    }
