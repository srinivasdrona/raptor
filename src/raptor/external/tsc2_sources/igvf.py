"""IGVF analysis-set/tabular-file metadata + downloaded-bytes verification
for the TSC2 VAMP-seq and SGE functional-dataset sources.

``verify_analysis_and_file`` is the single entry point: given an
already-fetched analysis-set metadata JSON document, an already-fetched
tabular-file metadata JSON document and the already-downloaded (still
gzip-compressed) file bytes, it checks the analysis-set accession/status,
the file accession/status/``controlled_access``/``assembly``/
``file_size``/``md5sum``, the exact ``/tabular-files/{accession}/@@download/
{accession}.tsv.gz`` download href, and verifies the downloaded bytes
against the published ``file_size``/``md5sum`` -- all against a
caller-supplied ``expected`` mapping, failing loud on ANY drift. The
returned record is ALWAYS ``STAGED_LICENCE_REVIEW_REQUIRED`` /
``REVIEW_REQUIRED`` -- IGVF's public release/access state is independent of,
and never a substitute for, a redistribution licence review; this module
never emits a classification-ready state. This module performs no network
I/O; all three inputs are injected as already-fetched bytes/text.

``assert_allowed_igvf_metadata_final_url``/``assert_allowed_igvf_download_
final_url`` are the IGVF-specific counterparts of
``raptor.external.tsc2_sources.endpoint.assert_allowed_final_url`` (which is
scoped to literature sources only): analysis-set/tabular-file metadata
requests must stay on ``api.data.igvf.org`` AND on the exact requested
accession path, while a tabular-file DOWNLOAD request's (possibly
redirected) final URL may land on EITHER ``api.data.igvf.org`` (exact
requested portal path) OR the official public object-storage host
(``igvf-public.s3.amazonaws.com``) -- no other host is ever added. The
real observed S3 redirect shape is an OPAQUE ``<date>/<uuid>/`` path
prefix, not the portal's ``/tabular-files/.../@@download/`` shape, so only
the S3 final path's BASENAME is bound and must be EXACTLY
``{requested_accession}.tsv.gz`` -- only explicitly nonsemantic signed
query values (e.g. ``X-Amz-Signature``) may differ, and the path prefix
ahead of the basename is unconstrained.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urlsplit

IGVF_METADATA_HOST = "api.data.igvf.org"
IGVF_DOWNLOAD_REDIRECT_HOST = "igvf-public.s3.amazonaws.com"

_HREF_PATTERN = re.compile(
    r"^/tabular-files/(?P<path_accession>[^/]+)/@@download/(?P<filename_accession>[^/]+)\.tsv\.gz$"
)


class IgvfVerificationError(ValueError):
    """Raised when IGVF analysis-set/tabular-file metadata cannot be parsed,
    or any observed value (accession, status, access, assembly, size, md5,
    download href) drifts from its caller-supplied expected pin, or the
    downloaded bytes do not match the published size/MD5."""


def _parse_json_object(raw_text: str, *, role: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise IgvfVerificationError(f"igvf {role} metadata is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise IgvfVerificationError(
            f"igvf {role} metadata must be a JSON object; got {type(payload).__name__}"
        )
    return payload


def _validate_href(href: Any, *, file_accession: str) -> str:
    if not isinstance(href, str) or not _HREF_PATTERN.match(href):
        raise IgvfVerificationError(
            "tabular-file href does not match the required "
            "/tabular-files/{accession}/@@download/{accession}.tsv.gz download path: "
            f"{href!r}"
        )
    match = _HREF_PATTERN.match(href)
    assert match is not None  # narrowed by the check above
    if (
        match.group("path_accession") != file_accession
        or match.group("filename_accession") != file_accession
    ):
        raise IgvfVerificationError(
            f"tabular-file href accession does not match the tabular-files file accession "
            f"{file_accession!r}: {href!r}"
        )
    return href


def verify_analysis_and_file(
    *,
    analysis_json: str,
    file_json: str,
    file_bytes: bytes,
    expected: dict[str, Any],
) -> dict[str, Any]:
    """Verify an IGVF analysis-set + tabular-file metadata pair and the
    downloaded (gzip-compressed) file bytes against ``expected`` (see
    ``expected_igvf_pin`` shape in ``configs/external/
    tsc2_source_ingestion_v1.yaml``). Raises ``IgvfVerificationError`` on
    ANY parse failure or drift."""
    analysis = _parse_json_object(analysis_json, role="analysis-set")
    file_meta = _parse_json_object(file_json, role="tabular-file")

    analysis_accession = analysis.get("accession")
    if analysis_accession != expected["analysis_set"]:
        raise IgvfVerificationError(
            f"igvf analysis-set accession mismatch: expected {expected['analysis_set']!r}, "
            f"observed {analysis_accession!r}"
        )

    file_accession = file_meta.get("accession")
    if file_accession != expected["file_accession"]:
        raise IgvfVerificationError(
            f"igvf tabular-file accession mismatch: expected {expected['file_accession']!r}, "
            f"observed {file_accession!r}"
        )

    required_status = expected["required_status"]
    analysis_status = analysis.get("status")
    file_status = file_meta.get("status")
    if analysis_status != required_status or file_status != required_status:
        raise IgvfVerificationError(
            f"igvf status does not match required {required_status!r}: "
            f"analysis status={analysis_status!r}, file status={file_status!r}"
        )

    controlled_access = file_meta.get("controlled_access")
    if controlled_access != expected["required_controlled_access"]:
        raise IgvfVerificationError(
            "igvf tabular-file controlled_access does not match the required public access "
            f"state: expected {expected['required_controlled_access']!r}, observed "
            f"{controlled_access!r}"
        )

    assembly = file_meta.get("assembly")
    if assembly != expected["expected_assembly"]:
        raise IgvfVerificationError(
            f"igvf tabular-file assembly mismatch: expected {expected['expected_assembly']!r}, "
            f"observed {assembly!r}"
        )

    expected_file_size = expected["expected_file_size"]
    metadata_file_size = file_meta.get("file_size")
    if metadata_file_size != expected_file_size:
        raise IgvfVerificationError(
            f"igvf tabular-file metadata file_size mismatch: expected {expected_file_size!r}, "
            f"observed {metadata_file_size!r} byte length"
        )
    observed_byte_length = len(file_bytes)
    if observed_byte_length != expected_file_size:
        raise IgvfVerificationError(
            "igvf downloaded byte length does not match the expected/published file_size: "
            f"expected {expected_file_size!r}, observed {observed_byte_length!r} bytes"
        )

    expected_md5 = expected["expected_md5"]
    metadata_md5 = file_meta.get("md5sum")
    if metadata_md5 != expected_md5:
        raise IgvfVerificationError(
            f"igvf tabular-file metadata md5sum mismatch: expected {expected_md5!r}, "
            f"observed {metadata_md5!r}"
        )
    observed_md5 = hashlib.md5(file_bytes).hexdigest()  # nosec B303/B324 - required published MD5 verification
    if observed_md5 != expected_md5:
        raise IgvfVerificationError(
            f"igvf downloaded file md5 does not match the published md5sum: expected "
            f"{expected_md5!r}, observed {observed_md5!r}"
        )

    href = _validate_href(file_meta.get("href"), file_accession=file_accession)

    return {
        "analysis_set": analysis_accession,
        "file_accession": file_accession,
        "status": analysis_status,
        "controlled_access": controlled_access,
        "assembly": assembly,
        "byte_length": observed_byte_length,
        "sha256": hashlib.sha256(file_bytes).hexdigest(),
        "md5": observed_md5,
        "href": href,
        "verification": "PUBLISHED_MD5_VERIFIED",
        "lifecycle_state": "STAGED_LICENCE_REVIEW_REQUIRED",
        "licence_state": "REVIEW_REQUIRED",
    }


def assert_allowed_igvf_metadata_final_url(*, requested_url: str, final_url: str) -> None:
    """Validate both the requested and the (possibly redirected) final URL
    for an IGVF analysis-set/tabular-file METADATA request against the
    fixed HTTPS ``api.data.igvf.org`` allowlist (metadata is never expected
    to redirect off-portal), AND bind ``final_url`` to the EXACT requested
    analysis-set/tabular-file accession path -- a redirect from one
    accession's metadata path to a *different* accession's metadata path
    (even on the same allowed host) is endpoint/identity substitution and
    is never acceptable."""
    for label, url in (("requested_url", requested_url), ("final_url", final_url)):
        parts = urlsplit(url)
        if parts.scheme != "https":
            raise IgvfVerificationError(
                f"igvf {label} scheme is not in the HTTPS allowlist: {parts.scheme!r} ({url!r})"
            )
        if parts.netloc != IGVF_METADATA_HOST:
            raise IgvfVerificationError(
                f"igvf {label} host is not the allowed {IGVF_METADATA_HOST!r} host: {url!r}"
            )

    requested_path = urlsplit(requested_url).path
    final_path = urlsplit(final_url).path
    if requested_path != final_path:
        raise IgvfVerificationError(
            f"igvf metadata final_url path {final_path!r} does not match the exact "
            f"requested analysis/file accession path {requested_path!r} (possible "
            "accession substitution)"
        )


def assert_allowed_igvf_download_final_url(*, requested_url: str, final_url: str) -> None:
    """Validate an IGVF tabular-file DOWNLOAD request: the requested URL
    must stay on the ``api.data.igvf.org`` portal and match the exact
    ``/tabular-files/{accession}/@@download/{accession}.tsv.gz`` pattern.
    The (possibly redirected) final URL may land on EITHER of exactly two
    hosts -- no new host is ever added:

    - ``api.data.igvf.org`` (no redirect happened): the final path must be
      the EXACT requested portal path.
    - ``igvf-public.s3.amazonaws.com`` (the observed real download
      redirect, e.g. ``https://igvf-public.s3.amazonaws.com/<date>/<uuid>/
      {accession}.tsv.gz?...`` -- an opaque date/uuid PREFIX, not the
      portal's ``/tabular-files/.../@@download/`` shape): only the final
      path's BASENAME is bound, and it must be EXACTLY
      ``{requested_accession}.tsv.gz`` -- a redirect may never substitute a
      different file's bytes. Signed query values (e.g.
      ``X-Amz-Signature``) are explicitly nonsemantic and are never
      compared, and nothing about the prefix ahead of the basename is
      constrained.

    Any other final host is rejected."""
    requested_parts = urlsplit(requested_url)
    if requested_parts.scheme != "https" or requested_parts.netloc != IGVF_METADATA_HOST:
        raise IgvfVerificationError(
            f"igvf download requested_url is not in the HTTPS {IGVF_METADATA_HOST!r} "
            f"allowlist: {requested_url!r}"
        )
    requested_match = _HREF_PATTERN.match(requested_parts.path)
    if requested_match is None or (
        requested_match.group("path_accession") != requested_match.group("filename_accession")
    ):
        raise IgvfVerificationError(
            "igvf download requested_url path does not match the required "
            f"/tabular-files/{{accession}}/@@download/{{accession}}.tsv.gz pattern: "
            f"{requested_url!r}"
        )
    requested_accession = requested_match.group("filename_accession")

    final_parts = urlsplit(final_url)
    if final_parts.scheme != "https":
        raise IgvfVerificationError(
            f"igvf download final_url scheme is not in the HTTPS allowlist: "
            f"{final_parts.scheme!r} ({final_url!r})"
        )

    if final_parts.netloc == IGVF_METADATA_HOST:
        if final_parts.path != requested_parts.path:
            raise IgvfVerificationError(
                f"igvf download final_url path {final_parts.path!r} does not match the "
                f"exact requested portal path {requested_parts.path!r} (possible "
                "endpoint substitution)"
            )
        return

    if final_parts.netloc == IGVF_DOWNLOAD_REDIRECT_HOST:
        final_basename = final_parts.path.rsplit("/", 1)[-1]
        expected_basename = f"{requested_accession}.tsv.gz"
        if final_basename != expected_basename:
            raise IgvfVerificationError(
                f"igvf download final_url S3 object basename {final_basename!r} does not "
                f"match the requested file accession's expected basename "
                f"{expected_basename!r} (possible S3 object substitution)"
            )
        return

    raise IgvfVerificationError(
        f"igvf download final_url host {final_parts.netloc!r} is outside the allowed "
        f"{IGVF_METADATA_HOST!r}/{IGVF_DOWNLOAD_REDIRECT_HOST!r} allowlist: {final_url!r}"
    )


__all__ = [
    "IgvfVerificationError",
    "IGVF_METADATA_HOST",
    "IGVF_DOWNLOAD_REDIRECT_HOST",
    "verify_analysis_and_file",
    "assert_allowed_igvf_metadata_final_url",
    "assert_allowed_igvf_download_final_url",
]
