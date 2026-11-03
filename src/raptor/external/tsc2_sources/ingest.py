"""Plan-driven, source-specific TSC2 ingestion over an injected transport.

``run_ingestion`` is the operator's single entry point: given a ``plan``
(``bundle_id``/``created_at``/``query`` plus a list of per-source plan
dicts, each carrying its own fixed ``request_url`` -- never a URL invented
or substituted here) and an injected ``transport`` callable, it dispatches
each source to a source-kind-specific handler (``pubmed``, ``litvar2``,
``pmc``, ``mavedb``, ``igvf``), which fetches (via the injected transport
ONLY -- never a real network call originating in this module), validates
the reported final URL, parses/verifies the response using the already-
committed literature parsers (``pubmed.py``/``litvar2.py``/``pmc.py``) or
this slice's functional-dataset verifiers (``mavedb.py``/``igvf.py``), and
builds the ``fetched_artifact``/``source_record`` pair ``bundle.py``
requires. On success across every planned source, the artifacts/sources are
assembled into a bundle manifest (``bundle.build_bundle_manifest``) and
published (``bundle.write_bundle_run``).

Any failure -- a transport exception, an endpoint-security violation, a
parser/verifier error, or an unknown ``source_kind`` -- is reported as a
``SourceIngestionError`` carrying the failing ``source_id``, a short
``invariant`` code (the underlying exception's class name) and the EXACT
``request_url`` that failed (always sanitized -- see ``_sanitize_url`` --
before it is ever stored or rendered): this module never substitutes a
different endpoint for a failing source and never silently drops a source
from the plan. Every per-source handler wraps its own known transport/
parser/verifier exceptions with a precisely-attributed ``request_url``, and
``run_ingestion`` itself additionally wraps ANY exception a handler might
still let escape (e.g. a malformed plan) as a last-resort safety net --
`SourceIngestionError` is always what a caller of ``run_ingestion`` sees,
never a raw/untyped exception. ``message`` -- not only ``request_url`` --
is ALSO scrubbed (``_redact_sensitive_text``) before it is ever stored or
rendered: a nested verifier's own message can itself embed a raw URL (e.g.
an IGVF endpoint verifier's rejection message quoting a signed final URL),
and that embedded value must never leak any sensitive query value either.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from raptor.atlas.citation import AtlasCitationResolutionError, normalize_identifier

from .bundle import build_bundle_manifest, write_bundle_run
from .endpoint import (
    EndpointSecurityError,
    TransportValidationError,
    build_pubmed_efetch_url,
    fetch_with_transport,
    request_with_transport,
)
from .igvf import (
    IgvfVerificationError,
    assert_allowed_igvf_download_final_url,
    assert_allowed_igvf_metadata_final_url,
    verify_analysis_and_file,
)
from .litvar2 import LitVarParseError, parse_gene_mappings
from .mavedb import (
    MaveSourceVerificationError,
    assert_allowed_mavedb_final_url,
    verify_scoreset,
)
from .pmc import PmcParseError, parse_fulltext_jats
from .pubmed import PubMedParseError, parse_efetch_xml, parse_esearch_payload

#: Query-string keys that must never be persisted/logged verbatim: optional
#: NCBI api_key/email inputs, and any AWS SigV4 signed-download credential
#: that may appear on an IGVF S3 redirect target.
_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "api_key",
        "email",
        "x-amz-signature",
        "x-amz-credential",
        "x-amz-security-token",
        "signature",
        "awsaccesskeyid",
    }
)

#: Matches a sensitive `key=value` occurrence ANYWHERE in arbitrary free
#: text -- not only a well-formed URL's own query string -- e.g. a raw URL
#: quoted/`repr`'d inside a nested verifier's own exception message (an
#: IGVF endpoint check rejecting a redirect embeds the full, still-signed
#: `final_url` in its message text). Longest keys are tried first so e.g.
#: `x-amz-signature` is matched as a whole instead of leaving a stray
#: `x-amz-` prefix in front of a `signature`-only redaction. Case-
#: insensitive on the key; only the value is ever replaced.
_SENSITIVE_TEXT_PATTERN = re.compile(
    r"(?i)\b(" + "|".join(re.escape(key) for key in sorted(_SENSITIVE_QUERY_KEYS, key=len, reverse=True))
    + r")=([^&\s'\")\]]*)"
)


def _redact_sensitive_text(text: str) -> str:
    """Redact every sensitive `key=value` occurrence found anywhere in
    ``text`` (see ``_SENSITIVE_TEXT_PATTERN``), preserving the key's own
    original casing and replacing only the value with ``REDACTED``. Unlike
    ``_sanitize_url``, this makes no assumption that ``text`` is itself a
    well-formed URL -- it also catches a URL (with its own query string)
    embedded inside another exception's free-form message text."""
    return _SENSITIVE_TEXT_PATTERN.sub(lambda match: f"{match.group(1)}=REDACTED", text)


class SourceIngestionError(RuntimeError):
    """Raised when one planned source fails to ingest. Carries the failing
    ``source_id``, a short ``invariant`` code (the underlying exception's
    class name -- never ``None``), and the exact ``request_url`` that was
    being fetched/parsed when the failure occurred (never a substituted
    endpoint). ``request_url`` -- both the stored attribute and the value
    embedded in this exception's rendered message -- is ALWAYS sanitized
    (``_sanitize_url``) before it is ever stored or rendered, and ``message``
    is ALSO scrubbed (``_redact_sensitive_text``) before rendering: a secret
    query value (``api_key``/``email``/an AWS SigV4 signed-download
    credential) must never reach an exception object, CLI stderr, a
    manifest, an artifact record or a log, here or anywhere downstream --
    including when a NESTED verifier's own message text already embeds a
    raw, still-signed URL."""

    def __init__(
        self,
        *,
        source_id: str,
        invariant: str,
        message: str,
        request_url: str | None = None,
    ) -> None:
        sanitized_request_url = _sanitize_url(request_url) if request_url else None
        sanitized_message = _redact_sensitive_text(message)
        self.source_id = source_id
        self.invariant = invariant
        self.request_url = sanitized_request_url
        rendered = f"{source_id}: {sanitized_message}"
        if sanitized_request_url:
            rendered = f"{rendered} (request_url={sanitized_request_url})"
        super().__init__(rendered)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sanitize_url(url: str) -> str:
    """Redact any sensitive query-string value (NCBI ``api_key``/``email``,
    or an AWS SigV4 signed-download credential) before a URL is ever
    persisted into an artifact record or the bundle manifest."""
    parts = urlsplit(url)
    if not parts.query:
        return url
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    sanitized = [
        (key, "REDACTED") if key.lower() in _SENSITIVE_QUERY_KEYS else (key, value)
        for key, value in pairs
    ]
    if sanitized == pairs:
        return url
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(sanitized), parts.fragment))


def _artifact_from_fetch(
    fetch: dict[str, Any],
    *,
    artifact_id: str,
    source_id: str,
    role: str,
    relative_path: str,
    fetched_at: str,
    verification: str,
) -> dict[str, Any]:
    body = fetch["body"]
    return {
        "artifact_id": artifact_id,
        "source_id": source_id,
        "role": role,
        "requested_url": _sanitize_url(fetch["requested_url"]),
        "final_url": _sanitize_url(fetch["final_url"]),
        "http_status": fetch["http_status"],
        "media_type": fetch["media_type"],
        "relative_path": relative_path,
        "byte_length": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "md5": hashlib.md5(body).hexdigest(),  # nosec B303 - non-cryptographic artifact fingerprint
        "fetched_at": fetched_at,
        "verification": verification,
    }


def _fetch_raw(url: str, transport: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
    """Call the injected ``transport`` through the shared, VALIDATED
    transport boundary (``endpoint.fetch_with_transport``) -- catching a
    raised transport exception and validating the response mapping's
    shape/types -- WITHOUT the literature-source host/path/query allowlist
    (no allowlist baked in here: the caller applies its own source-specific
    final-URL allowlist right after this returns). Raises
    ``TransportValidationError`` on ANY transport exception or malformed
    response."""
    return fetch_with_transport(requested_url=url, transport=transport)


def _normalize_identifier_safe(source_id: str, raw: str, *, request_url: str | None) -> str:
    try:
        return normalize_identifier(raw).canonical
    except AtlasCitationResolutionError as exc:
        raise SourceIngestionError(
            source_id=source_id,
            invariant=type(exc).__name__,
            message=f"could not canonicalize identifier {raw!r}: {exc}",
            request_url=request_url,
        ) from exc


def _handle_pubmed(source_plan: dict[str, Any], transport: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
    source_id = source_plan["source_id"]
    esearch_url = source_plan["request_url"]
    required_pmid = source_plan["required_pmid"]

    try:
        esearch_fetch = request_with_transport(requested_url=esearch_url, transport=transport)
    except (EndpointSecurityError, TransportValidationError) as exc:
        raise SourceIngestionError(
            source_id=source_id, invariant=type(exc).__name__, message=str(exc),
            request_url=esearch_url,
        ) from exc

    try:
        parsed = parse_esearch_payload(
            esearch_fetch["body"].decode("utf-8"),
            expected_db="pubmed",
            required_pmid=required_pmid,
        )
    except PubMedParseError as exc:
        raise SourceIngestionError(
            source_id=source_id, invariant=type(exc).__name__, message=str(exc),
            request_url=esearch_url,
        ) from exc

    efetch_url = build_pubmed_efetch_url(pmids=parsed["pmids"])
    try:
        efetch_fetch = request_with_transport(requested_url=efetch_url, transport=transport)
    except (EndpointSecurityError, TransportValidationError) as exc:
        raise SourceIngestionError(
            source_id=source_id, invariant=type(exc).__name__, message=str(exc),
            request_url=efetch_url,
        ) from exc

    try:
        rows = parse_efetch_xml(
            efetch_fetch["body"].decode("utf-8"), expected_pmids=parsed["pmids"]
        )
    except PubMedParseError as exc:
        raise SourceIngestionError(
            source_id=source_id, invariant=type(exc).__name__, message=str(exc),
            request_url=efetch_url,
        ) from exc

    fetched_at = _now_iso()
    esearch_artifact_id = f"{source_id}-esearch-json"
    efetch_artifact_id = f"{source_id}-efetch-xml"
    artifacts = [
        _artifact_from_fetch(
            esearch_fetch, artifact_id=esearch_artifact_id, source_id=source_id,
            role="PUBMED_ESEARCH_JSON", relative_path=f"pubmed/{source_id}-esearch.json",
            fetched_at=fetched_at, verification="HASHED",
        ),
        _artifact_from_fetch(
            efetch_fetch, artifact_id=efetch_artifact_id, source_id=source_id,
            role="PUBMED_EFETCH_XML", relative_path=f"pubmed/{source_id}-efetch.xml",
            fetched_at=fetched_at, verification="HASHED",
        ),
    ]
    bodies = {
        esearch_artifact_id: esearch_fetch["body"],
        efetch_artifact_id: efetch_fetch["body"],
    }
    source_record = {
        "source_id": source_id,
        "source_kind": "pubmed",
        "lifecycle_state": "STAGED_VERIFIED",
        "access_state": "PUBLIC",
        "licence_state": "PUBLIC_METADATA",
        "permitted_use": "NON_CLINICAL_DISCOVERY",
        "identifiers": {
            "required_pmid": _normalize_identifier_safe(
                source_id, f"PMID:{required_pmid}", request_url=esearch_url,
            ),
        },
        "artifact_ids": [esearch_artifact_id, efetch_artifact_id],
        "observations": {
            "count": parsed["count"],
            "returned_count": parsed["returned_count"],
            "is_truncated": parsed["is_truncated"],
            "metadata_row_count": len(rows),
        },
        "limitations": [
            "search results and metadata are discovery records, not proof of variant-level evidence",
        ],
    }
    return {
        "artifacts": artifacts,
        "bodies": bodies,
        "source": source_record,
        "truncation": {
            "count": parsed["count"],
            "returned_count": parsed["returned_count"],
            "is_truncated": parsed["is_truncated"],
        },
    }


def _handle_litvar2(source_plan: dict[str, Any], transport: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
    source_id = source_plan["source_id"]
    request_url = source_plan["request_url"]

    try:
        fetch = request_with_transport(requested_url=request_url, transport=transport)
    except (EndpointSecurityError, TransportValidationError) as exc:
        raise SourceIngestionError(
            source_id=source_id, invariant=type(exc).__name__, message=str(exc),
            request_url=request_url,
        ) from exc

    try:
        rows = parse_gene_mappings(fetch["body"].decode("utf-8"))
    except LitVarParseError as exc:
        raise SourceIngestionError(
            source_id=source_id, invariant=type(exc).__name__, message=str(exc),
            request_url=request_url,
        ) from exc

    fetched_at = _now_iso()
    artifact_id = f"{source_id}-gene-mappings-jsonl"
    artifacts = [
        _artifact_from_fetch(
            fetch, artifact_id=artifact_id, source_id=source_id,
            role="LITVAR2_GENE_MAPPINGS_JSONL", relative_path=f"litvar2/{source_id}-gene-mappings.jsonl",
            fetched_at=fetched_at, verification="HASHED",
        ),
    ]
    bodies = {artifact_id: fetch["body"]}
    source_record = {
        "source_id": source_id,
        "source_kind": "litvar2",
        "lifecycle_state": "STAGED_VERIFIED",
        "access_state": "PUBLIC",
        "licence_state": "PUBLIC_METADATA",
        "permitted_use": "NON_CLINICAL_DISCOVERY",
        "identifiers": {"gene": source_plan.get("gene", source_id)},
        "artifact_ids": [artifact_id],
        "observations": {
            "mapping_count": len(rows),
            "rsid_mapping_count": sum(1 for row in rows if row["rsid"] is not None),
            "rsidless_mapping_count": sum(1 for row in rows if row["rsid"] is None),
        },
        "limitations": [
            "every mapping is an untrusted lead, never a verified variant-publication association",
        ],
    }
    return {"artifacts": artifacts, "bodies": bodies, "source": source_record, "truncation": None}


def _handle_pmc(source_plan: dict[str, Any], transport: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
    source_id = source_plan["source_id"]
    request_url = source_plan["request_url"]
    expected_pmcid = source_plan["expected_pmcid"]

    try:
        fetch = request_with_transport(requested_url=request_url, transport=transport)
    except (EndpointSecurityError, TransportValidationError) as exc:
        raise SourceIngestionError(
            source_id=source_id, invariant=type(exc).__name__, message=str(exc),
            request_url=request_url,
        ) from exc

    try:
        parsed = parse_fulltext_jats(fetch["body"].decode("utf-8"), expected_pmcid=expected_pmcid)
    except PmcParseError as exc:
        raise SourceIngestionError(
            source_id=source_id, invariant=type(exc).__name__, message=str(exc),
            request_url=request_url,
        ) from exc

    fetched_at = _now_iso()
    artifact_id = f"{source_id}-fulltext-xml"
    artifacts = [
        _artifact_from_fetch(
            fetch, artifact_id=artifact_id, source_id=source_id,
            role="PMC_FULLTEXT_JATS_XML", relative_path=f"pmc/{source_id}-fulltext.xml",
            fetched_at=fetched_at, verification="HASHED",
        ),
    ]
    bodies = {artifact_id: fetch["body"]}
    lifecycle_state = (
        "STAGED_VERIFIED"
        if parsed["licence_state"] == "EXPLICIT_LICENSE_DECLARED"
        else "STAGED_LICENCE_REVIEW_REQUIRED"
    )
    source_record = {
        "source_id": source_id,
        "source_kind": "pmc",
        "lifecycle_state": lifecycle_state,
        "access_state": "PUBLIC",
        "licence_state": parsed["licence_state"],
        "permitted_use": "NON_CLINICAL_DISCOVERY",
        "identifiers": {
            "pmcid": _normalize_identifier_safe(source_id, parsed["pmcid"], request_url=request_url),
        },
        "artifact_ids": [artifact_id],
        "observations": {"raw_xml_sha256": parsed["raw_xml_sha256"]},
        "limitations": [
            "general PMC acquisition may not infer open reuse from the mere existence of a PMC record",
        ],
    }
    return {"artifacts": artifacts, "bodies": bodies, "source": source_record, "truncation": None}


def _handle_mavedb(source_plan: dict[str, Any], transport: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
    source_id = source_plan["source_id"]
    metadata_url = source_plan["metadata_request_url"]
    scores_url = source_plan["scores_request_url"]

    try:
        metadata_fetch = _fetch_raw(metadata_url, transport)
        assert_allowed_mavedb_final_url(
            requested_url=metadata_url, final_url=metadata_fetch["final_url"],
        )
    except (MaveSourceVerificationError, TransportValidationError) as exc:
        raise SourceIngestionError(
            source_id=source_id, invariant=type(exc).__name__, message=str(exc),
            request_url=metadata_url,
        ) from exc

    try:
        scores_fetch = _fetch_raw(scores_url, transport)
        assert_allowed_mavedb_final_url(requested_url=scores_url, final_url=scores_fetch["final_url"])
    except (MaveSourceVerificationError, TransportValidationError) as exc:
        raise SourceIngestionError(
            source_id=source_id, invariant=type(exc).__name__, message=str(exc),
            request_url=scores_url,
        ) from exc

    try:
        verified = verify_scoreset(
            metadata_json=metadata_fetch["body"].decode("utf-8"),
            scores_csv_bytes=scores_fetch["body"],
            expected_gene=source_plan["expected_gene"],
            expected_transcript=source_plan["expected_transcript"],
            expected_variant_count=source_plan["expected_variant_count"],
            expected_license=source_plan["expected_license"],
            expected_sha256=source_plan["expected_sha256"],
            expected_urn=source_plan.get("expected_urn"),
        )
    except MaveSourceVerificationError as exc:
        raise SourceIngestionError(
            source_id=source_id, invariant=type(exc).__name__, message=str(exc),
            request_url=scores_url,
        ) from exc

    fetched_at = _now_iso()
    metadata_artifact_id = f"{source_id}-metadata-json"
    scores_artifact_id = f"{source_id}-scores-csv"
    artifacts = [
        _artifact_from_fetch(
            metadata_fetch, artifact_id=metadata_artifact_id, source_id=source_id,
            role="MAVEDB_SCORESET_METADATA_JSON", relative_path=f"mavedb/{source_id}-metadata.json",
            fetched_at=fetched_at, verification="METADATA_ONLY",
        ),
        _artifact_from_fetch(
            scores_fetch, artifact_id=scores_artifact_id, source_id=source_id,
            role="MAVEDB_SCORES_CSV", relative_path=f"mavedb/{source_id}-scores.csv",
            fetched_at=fetched_at, verification="HASHED",
        ),
    ]
    bodies = {
        metadata_artifact_id: metadata_fetch["body"],
        scores_artifact_id: scores_fetch["body"],
    }
    source_record = {
        "source_id": source_id,
        "source_kind": "mavedb",
        "lifecycle_state": verified["lifecycle_state"],
        "access_state": "PUBLIC",
        "licence_state": "EXPLICIT_LICENSE_DECLARED",
        "permitted_use": "NON_CLINICAL_DISCOVERY",
        "identifiers": {"urn": source_plan.get("urn", source_id)},
        "artifact_ids": [metadata_artifact_id, scores_artifact_id],
        "observations": {
            "gene": verified["gene"],
            "transcript": verified["transcript"],
            "license": verified["license"],
            "variant_count": verified["variant_count"],
        },
        "limitations": [
            "functional scores remain non-gating pending a separately tested normalization "
            "and calibration slice",
        ],
    }
    return {"artifacts": artifacts, "bodies": bodies, "source": source_record, "truncation": None}


def _handle_igvf(source_plan: dict[str, Any], transport: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
    source_id = source_plan["source_id"]
    analysis_url = source_plan["analysis_request_url"]
    file_url = source_plan["file_request_url"]
    download_url = source_plan["download_request_url"]
    expected = source_plan["expected"]

    try:
        analysis_fetch = _fetch_raw(analysis_url, transport)
        assert_allowed_igvf_metadata_final_url(
            requested_url=analysis_url, final_url=analysis_fetch["final_url"],
        )
    except (IgvfVerificationError, TransportValidationError) as exc:
        raise SourceIngestionError(
            source_id=source_id, invariant=type(exc).__name__, message=str(exc),
            request_url=analysis_url,
        ) from exc

    try:
        file_fetch = _fetch_raw(file_url, transport)
        assert_allowed_igvf_metadata_final_url(requested_url=file_url, final_url=file_fetch["final_url"])
    except (IgvfVerificationError, TransportValidationError) as exc:
        raise SourceIngestionError(
            source_id=source_id, invariant=type(exc).__name__, message=str(exc),
            request_url=file_url,
        ) from exc

    try:
        download_fetch = _fetch_raw(download_url, transport)
        assert_allowed_igvf_download_final_url(
            requested_url=download_url, final_url=download_fetch["final_url"],
        )
    except (IgvfVerificationError, TransportValidationError) as exc:
        raise SourceIngestionError(
            source_id=source_id, invariant=type(exc).__name__, message=str(exc),
            request_url=download_url,
        ) from exc

    try:
        verified = verify_analysis_and_file(
            analysis_json=analysis_fetch["body"].decode("utf-8"),
            file_json=file_fetch["body"].decode("utf-8"),
            file_bytes=download_fetch["body"],
            expected=expected,
        )
    except IgvfVerificationError as exc:
        raise SourceIngestionError(
            source_id=source_id, invariant=type(exc).__name__, message=str(exc),
            request_url=download_url,
        ) from exc

    fetched_at = _now_iso()
    analysis_artifact_id = f"{source_id}-analysis-json"
    file_artifact_id = f"{source_id}-file-json"
    download_artifact_id = f"{source_id}-download-tsv-gz"
    artifacts = [
        _artifact_from_fetch(
            analysis_fetch, artifact_id=analysis_artifact_id, source_id=source_id,
            role="IGVF_ANALYSIS_SET_JSON", relative_path=f"igvf/{source_id}-analysis.json",
            fetched_at=fetched_at, verification="METADATA_ONLY",
        ),
        _artifact_from_fetch(
            file_fetch, artifact_id=file_artifact_id, source_id=source_id,
            role="IGVF_TABULAR_FILE_JSON", relative_path=f"igvf/{source_id}-file.json",
            fetched_at=fetched_at, verification="METADATA_ONLY",
        ),
        _artifact_from_fetch(
            download_fetch, artifact_id=download_artifact_id, source_id=source_id,
            role="IGVF_TABULAR_FILE_TSV_GZ",
            relative_path=f"igvf/{source_id}-{expected['file_accession']}.tsv.gz",
            fetched_at=fetched_at, verification="PUBLISHED_MD5_VERIFIED",
        ),
    ]
    bodies = {
        analysis_artifact_id: analysis_fetch["body"],
        file_artifact_id: file_fetch["body"],
        download_artifact_id: download_fetch["body"],
    }
    source_record = {
        "source_id": source_id,
        "source_kind": "igvf",
        "lifecycle_state": verified["lifecycle_state"],
        "access_state": "PUBLIC",
        "licence_state": verified["licence_state"],
        "permitted_use": "NON_CLINICAL_DISCOVERY",
        "identifiers": {
            "analysis_set": verified["analysis_set"],
            "file_accession": verified["file_accession"],
        },
        "artifact_ids": [analysis_artifact_id, file_artifact_id, download_artifact_id],
        "observations": {
            "status": verified["status"],
            "assembly": verified["assembly"],
            "byte_length": verified["byte_length"],
        },
        "limitations": [
            "redistribution is forbidden until a licence review is completed",
        ],
    }
    return {"artifacts": artifacts, "bodies": bodies, "source": source_record, "truncation": None}


_SOURCE_HANDLERS: dict[str, Callable[[dict[str, Any], Callable[[str], dict[str, Any]]], dict[str, Any]]] = {
    "pubmed": _handle_pubmed,
    "litvar2": _handle_litvar2,
    "pmc": _handle_pmc,
    "mavedb": _handle_mavedb,
    "igvf": _handle_igvf,
}


def run_ingestion(
    *,
    plan: dict[str, Any],
    transport: Callable[[str], dict[str, Any]],
    repo_root: Path | str,
    output_root: Path | str,
    run_name: str,
) -> dict[str, Any]:
    """Execute every source in ``plan['sources']`` against the injected
    ``transport``, then build and publish the bundle manifest. Raises
    ``SourceIngestionError`` (carrying ``source_id``/``invariant``/the
    exact failing ``request_url``) on the first source that fails to
    ingest -- no later source is processed, and no bundle is ever written
    for a plan that did not fully succeed."""
    sources_plan = plan.get("sources")
    if not isinstance(sources_plan, list) or not sources_plan:
        raise SourceIngestionError(
            source_id="__plan__",
            invariant="EmptyIngestionPlan",
            message="ingestion plan has no sources to process",
        )

    all_artifacts: list[dict[str, Any]] = []
    all_sources: list[dict[str, Any]] = []
    all_bodies: dict[str, bytes] = {}
    truncation: dict[str, Any] = {}

    for source_plan in sources_plan:
        source_id = source_plan.get("source_id")
        source_kind = source_plan.get("source_kind")
        handler = _SOURCE_HANDLERS.get(source_kind)
        if handler is None:
            raise SourceIngestionError(
                source_id=source_id or "__unknown__",
                invariant="UnknownSourceKind",
                message=f"no handler registered for source_kind {source_kind!r}",
                request_url=source_plan.get("request_url"),
            )
        try:
            result = handler(source_plan, transport)
        except SourceIngestionError:
            raise
        except Exception as exc:  # noqa: BLE001 - last-resort safety net: every handler
            # already wraps its own known transport/parser/verifier exceptions with a
            # precisely-attributed request_url, but this guarantees run_ingestion NEVER
            # lets a raw/unexpected exception (e.g. a malformed plan) escape unsanitized.
            fallback_request_url = (
                source_plan.get("request_url")
                or source_plan.get("metadata_request_url")
                or source_plan.get("analysis_request_url")
            )
            raise SourceIngestionError(
                source_id=source_id or "__unknown__",
                invariant=type(exc).__name__,
                message=(
                    f"unhandled {type(exc).__name__} while ingesting source (the underlying "
                    "exception message is withheld to avoid leaking transport-layer secrets)"
                ),
                request_url=fallback_request_url,
            ) from exc
        all_artifacts.extend(result["artifacts"])
        all_sources.append(result["source"])
        all_bodies.update(result["bodies"])
        if result.get("truncation") is not None:
            truncation[source_id] = result["truncation"]

    manifest = build_bundle_manifest(
        bundle_id=plan["bundle_id"],
        created_at=plan["created_at"],
        query=plan["query"],
        artifacts=all_artifacts,
        sources=all_sources,
        truncation=truncation,
        boundaries={"network": "injected", "external_output_only": True},
    )

    artifact_payloads = {
        artifact["relative_path"]: all_bodies[artifact["artifact_id"]] for artifact in all_artifacts
    }

    write_result = write_bundle_run(
        repo_root=Path(repo_root),
        output_root=Path(output_root),
        run_name=run_name,
        manifest=manifest,
        artifact_payloads=artifact_payloads,
    )

    return {"manifest": manifest, "write_result": write_result}


__all__ = [
    "SourceIngestionError",
    "run_ingestion",
]
