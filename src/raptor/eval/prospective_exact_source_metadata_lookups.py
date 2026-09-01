"""raptor.eval.prospective_exact_source_metadata_lookups -- the ADR-0020
hard-wired, production-owned implementations of the
`published_archive_date_lookup`/`official_md5_lookup` ports consumed by
`raptor.eval.prospective_freeze.execute_transport_and_raw_freeze`.

Independent review finding (live-transport-bypass, round 5): confirmed
live `--execute` acquisition must import/execute ZERO caller-selected
Python/plugin code before the real archive GET. This module is the ONE
production implementation for both ports. It is imported *statically* --
a plain `import` statement at the top of
`scripts/run_clinvar_2026_08_prospective_freeze.py`, resolved once at
Python's own module-load time, never from a runtime string -- and there
is no CLI option, environment variable, or config value anywhere in this
repository that can substitute a different module for either port during
a confirmed live `--execute` run. `--published-archive-date-lookup`/
`--official-md5-lookup` were removed from the CLI entirely (not merely
defaulted): supplying either flag is an "unrecognized arguments" argparse
failure before anything else runs. See that script's module docstring
for the full history of this finding.

Round 6 (this module): both ports are now REAL, working implementations,
never permanent fail-closed stubs:

* `published_archive_date_lookup` returns a PINNED, versioned, reviewed
  registration constant -- `dataset_registration.metadata_source_pins
  .published_archive_date`/`.published_archive_date_authority` in
  `docs/project/specs/clinvar-2026-08-prospective-amendment-v2.yaml`,
  read fresh (never cached) on every call, exactly like
  `raptor.eval.prospective_exact_source_transport._load_registered_contract`
  reads `dataset_registration.exact_url`. It NEVER infers the date from
  the live HTTP `Last-Modified` header (that is transport metadata only,
  per `dataset_registration.prior_head_observation.evidentiary_role`) and
  NEVER fetches NCBI's general maintenance/use documentation pages at
  execution time -- the authoritative evidence for this registration's
  one pinned date (NCBI's tab_delimited maintenance-and-use documentation
  and archive README both describe a first-Thursday-of-month monthly
  release cycle; 2026-08's first Thursday is 2026-08-06, matching this
  registration's own preregistered HEAD observation) was reviewed once,
  by a human, and is recorded as a spec constant -- never re-derived at
  runtime.
* `official_md5_lookup` performs exactly ONE bounded, read-only HTTPS GET
  against the ONE pinned checksum URL
  (`dataset_registration.metadata_source_pins.official_md5_url` -- the
  public NCBI ClinVar adjacent "<archive>.md5" companion convention for
  this registration's exact archive object; there is no alternate URL,
  fallback, or directory listing this function will ever consult). The
  checksum digest itself is a genuinely live fact this repository cannot
  pin ahead of time (NCBI publishes it only in that companion file
  alongside the live monthly archive) -- unlike the transport's own
  archive GET, a real network call is therefore unavoidable here, but
  every policy constraint around it is closed and pinned exactly like
  the main transport: the URL (exact match against the registered
  archive URL for the incoming `url` argument, and the ONE pinned
  checksum URL for the actual GET), no redirect (any 3xx response is
  rejected before its body is read), TLS certificate verification always
  on (`ssl.create_default_context`, `CERT_REQUIRED`), no proxy (this
  module never reads `HTTP_PROXY`/`HTTPS_PROXY`, and `http.client
  .HTTPSConnection` performs no proxying on its own) and no
  `Authorization`/`Proxy-Authorization` header, a strict bounded timeout,
  a small hard response-size ceiling (the body is read via one single
  bounded `read()` call, never an unbounded read), exact 32-hex MD5
  parsing, and -- when the response includes a filename (the common
  `md5sum`-style `"<hex>  <filename>"`/`"<hex> *<filename>"` output
  format) -- an exact match against
  `metadata_source_pins.official_md5_expected_filename`. A bare hex
  digest with no filename at all is also accepted (some servers publish
  only the digest); there is no partial/fuzzy filename match in either
  direction.

Both ports' network/TLS hooks (`official_md5_lookup`'s `connection_factory`/
`tls_context_factory` keyword parameters) are caller-injectable purely as
an offline-test seam, exactly like `prospective_exact_source_transport
.build_transport`'s own hooks -- the real defaults
(`http.client.HTTPSConnection`, `ssl.create_default_context`) are the ONLY
real network path this module ever provides, and the live CLI
(`scripts/run_clinvar_2026_08_prospective_freeze.py`) never passes either
keyword: it calls `official_md5_lookup(exact_url)` with only the one
positional port argument, so there is no CLI flag, environment variable,
or config value anywhere that can select a different network
implementation for a confirmed live `--execute` run. Tests that need to
observe the CLI's own end-to-end wiring patch this module's two
attributes directly with `monkeypatch.setattr` -- a known, static,
production-owned symbol, never a dynamically-resolved `"module:callable"`
string.
"""
from __future__ import annotations

import http.client
import re
import ssl
from datetime import date
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import yaml

__all__ = [
    "MetadataLookupError",
    "MetadataLookupConfigurationError",
    "MetadataLookupPolicyError",
    "URL_POLICY_REASON",
    "REDIRECT_POLICY_REASON",
    "STATUS_POLICY_REASON",
    "SIZE_POLICY_REASON",
    "PARSE_POLICY_REASON",
    "FILENAME_POLICY_REASON",
    "published_archive_date_lookup",
    "official_md5_lookup",
]

#: This file's fixed location is `<repo>/src/raptor/eval/
#: prospective_exact_source_metadata_lookups.py`, so the repo root is
#: always this file's great-grandparent (mirrors
#: `prospective_exact_source_transport._REPO_ROOT`).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_REGISTRATION_SPEC_PATH = (
    _REPO_ROOT / "docs" / "project" / "specs" / "clinvar-2026-08-prospective-amendment-v2.yaml"
)

#: Closed lookup-policy reason-code vocabulary (mirrors
#: `prospective_exact_source_transport`'s own closed vocabulary shape).
URL_POLICY_REASON = "EXACT_REGISTERED_URL_REQUIRED"
REDIRECT_POLICY_REASON = "REDIRECT_NOT_ALLOWED"
STATUS_POLICY_REASON = "CHECKSUM_STATUS_NOT_OK"
SIZE_POLICY_REASON = "CHECKSUM_RESPONSE_TOO_LARGE"
PARSE_POLICY_REASON = "CHECKSUM_RESPONSE_UNPARSEABLE"
FILENAME_POLICY_REASON = "CHECKSUM_FILENAME_MISMATCH"

_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})

#: A small, hard, non-configurable response-size ceiling for the checksum
#: GET -- a legitimate `.md5` companion file is well under 100 bytes; this
#: is deliberately generous headroom while still being "small" (never an
#: unbounded read of any kind).
_MAX_MD5_RESPONSE_BYTES = 4096

#: Strict, non-configurable request timeout for the checksum GET.
_MD5_GET_TIMEOUT_SECONDS = 30.0

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
#: Standard `md5sum`-family output: a bare 32-hex digest, optionally
#: followed by whitespace and an (optionally `*`-prefixed, "binary mode")
#: filename. Matches the WHOLE (already-stripped) response text -- no
#: partial match, no trailing garbage tolerated.
_MD5_LINE_RE = re.compile(r"^([0-9a-fA-F]{32})(?:[ \t]+\*?(\S+))?$")


class MetadataLookupError(Exception):
    """Base class for every typed `prospective_exact_source_metadata_lookups`
    failure (registration-spec configuration failures are never a policy
    rejection -- see `MetadataLookupConfigurationError`)."""


class MetadataLookupConfigurationError(MetadataLookupError):
    """The registration spec itself is missing, malformed, or missing a
    required `metadata_source_pins` entry -- a repository configuration
    defect, never a per-call policy rejection. Both lookup ports still
    fail closed on this (never a silent default), but callers should
    never see this in normal operation once the spec is correctly
    pinned."""


class MetadataLookupPolicyError(MetadataLookupError):
    """A closed lookup-policy rejection -- an unregistered/mismatched
    archive URL (`URL_POLICY_REASON`), a disallowed checksum-GET redirect
    (`REDIRECT_POLICY_REASON`), a non-200 checksum status
    (`STATUS_POLICY_REASON`), an oversized checksum response
    (`SIZE_POLICY_REASON`), an unparseable checksum body
    (`PARSE_POLICY_REASON`), or a checksum-response filename that does
    not match the registered archive filename (`FILENAME_POLICY_REASON`).
    `.reason_code` is always one of the closed reason codes above;
    `.reason` is always a non-blank human-readable string."""

    def __init__(self, reason_code: str, reason: str) -> None:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("MetadataLookupPolicyError requires a non-blank reason")
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def _load_registered_metadata_pins() -> dict[str, str]:
    """Read `dataset_registration.exact_url` and
    `dataset_registration.metadata_source_pins` fresh from the
    registration spec -- never cached, never defaulted, never supplied by
    a caller. Raises `MetadataLookupConfigurationError` (never a policy
    error) if the spec is missing or malformed: a broken pin is a
    configuration failure, not a per-call policy rejection."""
    try:
        raw = _REGISTRATION_SPEC_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise MetadataLookupConfigurationError(f"unable to read registration spec: {exc}") from exc
    try:
        loaded = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise MetadataLookupConfigurationError(f"registration spec is not valid YAML: {exc}") from exc
    if not isinstance(loaded, dict):
        raise MetadataLookupConfigurationError("registration spec must parse to a mapping")
    dataset_registration = loaded.get("dataset_registration")
    if not isinstance(dataset_registration, dict):
        raise MetadataLookupConfigurationError("registration spec missing dataset_registration mapping")
    registered_url_value = dataset_registration.get("exact_url")
    if not isinstance(registered_url_value, str) or not registered_url_value:
        raise MetadataLookupConfigurationError("dataset_registration.exact_url must be a non-blank string")
    registered_url = registered_url_value
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
            "dataset_registration.exact_url must be the pinned direct NCBI HTTPS URL without credentials, port, query, or fragment"
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

    official_md5_url = pins.get("official_md5_url")
    parsed_md5_url = urlsplit(str(official_md5_url))
    if (
        parsed_md5_url.scheme != "https"
        or parsed_md5_url.hostname != parsed_registered_url.hostname
        or not parsed_md5_url.path
        or parsed_md5_url.username is not None
        or parsed_md5_url.password is not None
        or parsed_md5_url.port is not None
        or parsed_md5_url.query
        or parsed_md5_url.fragment
        or str(official_md5_url) != f"{registered_url}.md5"
    ):
        raise MetadataLookupConfigurationError(
            "metadata_source_pins.official_md5_url must be exactly dataset_registration.exact_url + '.md5'"
        )
    official_md5_expected_filename = pins.get("official_md5_expected_filename")
    if not isinstance(official_md5_expected_filename, str) or not official_md5_expected_filename.strip():
        raise MetadataLookupConfigurationError(
            "metadata_source_pins.official_md5_expected_filename must be a non-blank string"
        )

    return {
        "registered_url": registered_url,
        "published_archive_date": published_archive_date,
        "published_archive_date_authority": published_archive_date_authority,
        "official_md5_url": str(official_md5_url),
        "official_md5_host": parsed_md5_url.hostname,
        "official_md5_path": parsed_md5_url.path,
        "official_md5_expected_filename": official_md5_expected_filename,
    }


def _require_registered_url(url: str, pins: dict[str, str]) -> None:
    if url != pins["registered_url"]:
        raise MetadataLookupPolicyError(
            URL_POLICY_REASON, f"url is not the exact registered archive URL: {url!r}"
        )


def _first_header(raw_headers: Any, name: str) -> str | None:
    name_lower = name.lower()
    for entry in raw_headers or ():
        if isinstance(entry, (list, tuple)) and len(entry) == 2 and str(entry[0]).lower() == name_lower:
            return str(entry[1])
    return None


def published_archive_date_lookup(url: str) -> dict[str, Any]:
    """Hard-wired production `published_archive_date_lookup` port. Rejects
    any `url` other than the exact registered archive URL
    (`URL_POLICY_REASON`) before returning anything. On success, returns
    the PINNED `metadata_source_pins.published_archive_date`/
    `.published_archive_date_authority` read fresh from the registration
    spec -- never inferred from a live HTTP response, never fetched from
    a general documentation page at execution time. Never opens a
    socket."""
    pins = _load_registered_metadata_pins()
    _require_registered_url(url, pins)
    return {
        "published_archive_date": pins["published_archive_date"],
        "source_identity": pins["published_archive_date_authority"],
    }


def official_md5_lookup(
    url: str,
    *,
    connection_factory: Callable[..., Any] = http.client.HTTPSConnection,
    tls_context_factory: Callable[[], Any] = ssl.create_default_context,
) -> dict[str, Any]:
    """Hard-wired production `official_md5_lookup` port. Rejects any `url`
    other than the exact registered archive URL (`URL_POLICY_REASON`)
    before opening any connection. On success, performs exactly ONE
    bounded, read-only HTTPS GET against the ONE pinned
    `metadata_source_pins.official_md5_url` -- no alternate URL, fallback,
    or directory listing is ever consulted -- and returns the parsed
    32-hex MD5 digest plus the checksum URL itself as `source_identity`.

    `connection_factory`/`tls_context_factory` are caller-injectable
    purely as an offline-test seam (mirrors
    `prospective_exact_source_transport.build_transport`'s own hooks); the
    live CLI never passes either keyword, so confirmed live `--execute`
    always uses the real defaults (`http.client.HTTPSConnection`,
    `ssl.create_default_context` -- TLS verification always on)."""
    pins = _load_registered_metadata_pins()
    _require_registered_url(url, pins)

    context = tls_context_factory()
    if (
        getattr(context, "check_hostname", None) is not True
        or getattr(context, "verify_mode", None) != ssl.CERT_REQUIRED
    ):
        raise MetadataLookupConfigurationError(
            "official MD5 HTTPS transport requires hostname checking and CERT_REQUIRED certificate verification"
        )
    conn = connection_factory(pins["official_md5_host"], timeout=_MD5_GET_TIMEOUT_SECONDS, context=context)
    try:
        conn.request("GET", pins["official_md5_path"], headers={})
        response = conn.getresponse()
        status = int(response.status)
        if status in _REDIRECT_STATUS_CODES:
            location = _first_header(response.getheaders(), "location")
            raise MetadataLookupPolicyError(
                REDIRECT_POLICY_REASON,
                f"checksum GET redirected (status={status}, location={location!r}); "
                "no redirect is ever followed, on- or off-host/path alike",
            )
        if status != 200:
            raise MetadataLookupPolicyError(
                STATUS_POLICY_REASON, f"checksum GET returned non-200, non-redirect status={status}"
            )
        # One single bounded read -- never an unbounded `response.read()`.
        # Requesting one byte past the ceiling lets an over-length body be
        # detected and rejected without ever trusting an unbounded read.
        raw = response.read(_MAX_MD5_RESPONSE_BYTES + 1)
        if len(raw) > _MAX_MD5_RESPONSE_BYTES:
            raise MetadataLookupPolicyError(
                SIZE_POLICY_REASON, f"checksum response exceeded the {_MAX_MD5_RESPONSE_BYTES}-byte ceiling"
            )
    finally:
        conn.close()

    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise MetadataLookupPolicyError(PARSE_POLICY_REASON, f"checksum response is not ASCII: {exc}") from exc
    match = _MD5_LINE_RE.match(text.strip())
    if match is None:
        raise MetadataLookupPolicyError(
            PARSE_POLICY_REASON, f"checksum response is not a recognizable md5 line: {text.strip()!r}"
        )
    official_md5, filename = match.group(1).lower(), match.group(2)
    if filename is not None and filename != pins["official_md5_expected_filename"]:
        raise MetadataLookupPolicyError(
            FILENAME_POLICY_REASON,
            f"checksum filename {filename!r} does not match the registered archive filename "
            f"{pins['official_md5_expected_filename']!r}",
        )
    return {"official_md5": official_md5, "source_identity": pins["official_md5_url"]}
