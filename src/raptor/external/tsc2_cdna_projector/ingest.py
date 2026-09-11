"""RAPTOR v2 cliPE cDNA -> GRCh38 SPDI projector -- frozen-input validation
and the pure, offline-transport-injected acquisition entry point.

``validate_frozen_scores_input`` re-verifies the frozen MaveDB TSC2 cliPE
scores CSV against this slice's pinned header/row-count/sha256/byte_length
(spec ``inputs.source_bundle.scores_artifact``), rejects a duplicate
``hgvs_nt`` and any ``hgvs_nt`` shape outside the frozen SNV/equal-length-
DELINS composition (spec ``input_composition.shapes``), and returns one
parsed record per ``source_row`` (1-based, ascending, matching the file's
own row order -- spec ``deterministic_ordering``).

``validate_reference_fasta_checksum`` verifies the pinned ``NC_000016.10``
FASTA's actual sha256 -- this MUST be checked, and MUST succeed, before any
row is ever handed to the NCBI Variation Services projector (spec
``fasta_validation.precondition``).

``project_clipe_rows`` is the single, pure orchestration entry point
``scripts/fetch_tsc2_clipe_cdna_spdi_projector.py`` calls: it verifies the
reference FASTA checksum FIRST (before validating the scores CSV or
issuing any request), then the frozen scores CSV, then walks every row in
ascending ``source_row`` order performing the exact step1 (contextuals) ->
step2 (canonical_representative) sequence over the INJECTED ``transport``
callable -- never a real network call -- with rate-limiting/retry driven
entirely by the injected ``sleep`` callable (so no test ever sleeps for
real). A permanent, row-scoped failure (invalid HGVS, ambiguous SPDIs, an
unpinned genome, a FASTA mismatch, exhausted HTTP/transport retries, ...)
records a structured mapping row and continues to the next row (spec
``error_states.conservation_rule``: exactly one mapping row per
``source_row``, no silent drops). A binding/allowlist violation
(``endpoint.ProjectorEndpointSecurityError``) is NEVER caught here -- it
propagates straight out and aborts the whole run, per spec
``rate_limits_retries.row_failure_vs_run_abort.run_abort``.

This module performs no network I/O and never imports ``raptor.scorer``,
``raptor.eval``, ``raptor.packet``, ``raptor.census``, ``raptor.kb``,
``raptor.atlas`` or ``raptor.rescuescreen``.
"""
from __future__ import annotations

import csv
import hashlib
import io
import random
import ssl
import time
from pathlib import Path
from typing import Any, Callable

from raptor.external.tsc2_sources.bundle import compute_bundle_content_hash as _compute_source_bundle_content_hash

from .endpoint import (
    ProjectorTransportValidationError,
    assert_allowed_projector_final_url,
    build_step1_hgvs_contextuals_url,
    build_step2_spdi_canonical_representative_url,
    fetch_raw_with_transport,
)
from .model import GENE, ClipeCdnaSpdiMappingRow, ProjectionContractError, classify_variant_shape
from .parse import Step1SchemaError, Step2SchemaError, parse_step1_contextuals_response, parse_step2_canonical_representative_response

_CHUNK_SIZE = 1024 * 1024  # 1 MiB

#: step1 parse-error reason -> mapping status.
_STEP1_REASON_TO_STATUS: dict[str, str] = {
    "INVALID_HGVS": "STEP1_INVALID_HGVS",
    "AMBIGUOUS_SPDIS": "STEP1_AMBIGUOUS_SPDIS",
    "UNEXPECTED_SEQ_ID": "STEP1_UNEXPECTED_SEQ_ID",
    "NON_ACGT_ALLELE": "NON_ACGT_ALLELE",
    "WARNINGS_PRESENT": "STEP1_SCHEMA_VIOLATION",
    "SCHEMA_VIOLATION": "STEP1_SCHEMA_VIOLATION",
}
#: step2 parse-error reason -> mapping status.
_STEP2_REASON_TO_STATUS: dict[str, str] = {
    "NON_PINNED_GENOME": "STEP2_NON_PINNED_GENOME",
    "NON_ACGT_ALLELE": "NON_ACGT_ALLELE",
    "WARNINGS_PRESENT": "STEP2_SCHEMA_VIOLATION",
    "SCHEMA_VIOLATION": "STEP2_SCHEMA_VIOLATION",
}


class ProjectorAcquisitionError(RuntimeError):
    """Base error for this slice's ingest-time domain errors."""


class FrozenInputError(ProjectorAcquisitionError):
    """Raised when the frozen MaveDB TSC2 cliPE scores CSV's header, row
    count, sha256, byte length, or per-row ``hgvs_nt`` shape/duplication
    does not match this slice's frozen expectations."""


class ReferenceIntegrityError(ProjectorAcquisitionError):
    """Raised when the pinned ``NC_000016.10`` reference FASTA is missing
    or its actual sha256 does not match the pinned value. Always raised
    (and always succeeds) before any row is handed to the projector."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_reference_fasta_checksum(*, reference_fasta_path: Path | str, expected_sha256: str) -> str:
    """Return the actual sha256 of ``reference_fasta_path`` if it matches
    ``expected_sha256``; otherwise raise ``ReferenceIntegrityError``. Also
    raises if the file does not exist. This MUST be called -- and MUST
    succeed -- before any row is projected against NCBI Variation
    Services (spec ``fasta_validation.precondition``)."""
    path = Path(reference_fasta_path)
    if not path.is_file():
        raise ReferenceIntegrityError(
            f"pinned reference FASTA not found at {path}; refusing to project any row without "
            "a verified reference"
        )
    actual = _sha256_file(path)
    if actual.lower() != str(expected_sha256).lower():
        raise ReferenceIntegrityError(
            f"reference FASTA checksum mismatch at {path}: pinned {expected_sha256!r} != actual "
            f"sha256 {actual!r}; refusing to project any row against an unverified/altered "
            "reference"
        )
    return actual


def validate_frozen_source_bundle_manifest(
    *,
    source_manifest: dict[str, Any],
    expected_bundle_id: str,
    expected_manifest_content_hash: str,
    expected_scores_artifact: dict[str, Any],
) -> None:
    """Re-verify an already-published TSC2 source-ingestion bundle
    manifest (``raptor.external.tsc2_sources.bundle``) BEFORE its frozen
    ``mavedb_clipe`` scores CSV is read/used for projection.

    Recomputes the manifest's own canonical content hash via
    ``tsc2_sources.bundle.compute_bundle_content_hash`` (the SAME helper
    that module itself uses -- never a reimplementation) and requires it
    to match BOTH the manifest's own recorded ``content_hash`` field
    (internal self-consistency -- a manifest whose recorded hash was
    tampered with is rejected even if every artifact record is otherwise
    untouched) AND the caller's pinned ``expected_manifest_content_hash``.
    Requires ``bundle_id`` to equal ``expected_bundle_id``.

    Locates exactly one artifact whose ``artifact_id`` equals
    ``expected_scores_artifact["artifact_id"]`` and requires its
    ``source_id``/``relative_path``/``sha256``/``byte_length`` to exactly
    match the pinned ``expected_scores_artifact``. Then rejects the WHOLE
    manifest if any OTHER artifact either: (a) shares the pinned scores
    artifact's exact ``relative_path`` under a different ``artifact_id``
    (a duplicate), or (b) has an ``artifact_id`` that is a near-collision
    PREFIX of the pinned scores artifact_id (a decoy, e.g.
    ``"<pinned-id>-decoy"``) -- a legitimate sibling artifact from the
    same source (e.g. a MaveDB metadata JSON alongside the scores CSV)
    never collides with either rule, since it uses an unrelated
    ``artifact_id``/``relative_path``.

    Raises ``FrozenInputError`` on any of the above violations."""
    if not isinstance(source_manifest, dict):
        raise FrozenInputError("source bundle manifest must be a mapping")

    recomputed = _compute_source_bundle_content_hash(source_manifest)
    recorded = source_manifest.get("content_hash")
    if recomputed != recorded:
        raise FrozenInputError(
            f"source bundle manifest content_hash is not internally consistent: recorded "
            f"{recorded!r} != recomputed {recomputed!r}; refusing to trust a manifest whose "
            "own recorded hash has been tampered with"
        )
    if recomputed != expected_manifest_content_hash:
        raise FrozenInputError(
            f"source bundle manifest content_hash does not match the pinned expectation: "
            f"{recomputed!r} != {expected_manifest_content_hash!r}"
        )

    bundle_id = source_manifest.get("bundle_id")
    if bundle_id != expected_bundle_id:
        raise FrozenInputError(
            f"source bundle manifest bundle_id {bundle_id!r} does not match the pinned "
            f"expectation {expected_bundle_id!r}"
        )

    artifacts = source_manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise FrozenInputError("source bundle manifest artifacts must be a list")

    expected_artifact_id = expected_scores_artifact["artifact_id"]
    expected_relative_path = expected_scores_artifact["relative_path"]

    matches = [
        artifact
        for artifact in artifacts
        if isinstance(artifact, dict) and artifact.get("artifact_id") == expected_artifact_id
    ]
    if len(matches) != 1:
        raise FrozenInputError(
            f"source bundle manifest must contain exactly one artifact with artifact_id "
            f"{expected_artifact_id!r}, found {len(matches)}"
        )
    scores_artifact = matches[0]
    for field_name in ("source_id", "relative_path", "sha256", "byte_length"):
        expected_value = expected_scores_artifact.get(field_name)
        actual_value = scores_artifact.get(field_name)
        if actual_value != expected_value:
            raise FrozenInputError(
                f"source bundle manifest artifact {expected_artifact_id!r} field {field_name!r} "
                f"does not match the pinned expectation: {actual_value!r} != {expected_value!r}"
            )

    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        artifact_id = artifact.get("artifact_id")
        if artifact_id == expected_artifact_id:
            continue
        if isinstance(artifact_id, str) and artifact_id.startswith(expected_artifact_id):
            raise FrozenInputError(
                f"source bundle manifest contains a decoy artifact_id {artifact_id!r} that is a "
                f"near-collision prefix of the pinned scores artifact_id {expected_artifact_id!r}"
            )
        if artifact.get("relative_path") == expected_relative_path:
            raise FrozenInputError(
                "source bundle manifest contains a duplicate artifact at relative_path "
                f"{expected_relative_path!r} under a different artifact_id {artifact_id!r}"
            )


def validate_frozen_scores_input(
    *,
    csv_text: str,
    expected_header: list[str],
    expected_rows: int,
    expected_sha256: str,
    expected_byte_length: int,
    transcript: str,
) -> list[dict[str, Any]]:
    """Re-verify the frozen MaveDB cliPE scores CSV and return one parsed
    record per data row: ``{"source_row", "accession", "hgvs_nt",
    "hgvs_c", "variant_shape"}``, in ascending ``source_row`` (1-based,
    matching file order). Raises ``FrozenInputError`` on any header/row-
    count/hash/byte-length mismatch, duplicate ``hgvs_nt``, or ``hgvs_nt``
    shape outside the frozen SNV/equal-length-DELINS composition."""
    payload = csv_text.encode("utf-8")
    if len(payload) != expected_byte_length:
        raise FrozenInputError(
            f"scores CSV byte_length mismatch: expected {expected_byte_length!r}, observed "
            f"{len(payload)!r}"
        )
    actual_sha256 = hashlib.sha256(payload).hexdigest()
    if actual_sha256.lower() != str(expected_sha256).lower():
        raise FrozenInputError(
            f"scores CSV sha256 mismatch: expected {expected_sha256!r}, observed "
            f"{actual_sha256!r}"
        )

    rows = list(csv.reader(io.StringIO(csv_text)))
    if not rows:
        raise FrozenInputError("scores CSV is empty (no header row)")
    header = rows[0]
    if header != list(expected_header):
        raise FrozenInputError(f"scores CSV unexpected header {header!r} (expected {list(expected_header)!r})")
    data_rows = rows[1:]
    if len(data_rows) != expected_rows:
        raise FrozenInputError(f"scores CSV expected exactly {expected_rows} rows, found {len(data_rows)}")

    seen_hgvs_nt: set[str] = set()
    parsed: list[dict[str, Any]] = []
    for index, values in enumerate(data_rows, start=1):
        if len(values) != len(header):
            raise FrozenInputError(f"scores CSV row {index}: has {len(values)} fields, expected {len(header)}")
        record = dict(zip(header, values))
        accession = record["accession"]
        if not isinstance(accession, str) or not accession.strip():
            raise FrozenInputError(f"scores CSV row {index}: accession must be a non-blank string")
        hgvs_nt = record["hgvs_nt"]
        if hgvs_nt in seen_hgvs_nt:
            raise FrozenInputError(f"scores CSV row {index}: duplicate hgvs_nt {hgvs_nt!r}")
        seen_hgvs_nt.add(hgvs_nt)
        try:
            variant_shape = classify_variant_shape(hgvs_nt)
        except ProjectionContractError as exc:
            raise FrozenInputError(f"scores CSV row {index}: {exc}") from exc
        parsed.append(
            {
                "source_row": index,
                "accession": accession,
                "hgvs_nt": hgvs_nt,
                "hgvs_c": f"{transcript}:{hgvs_nt}",
                "variant_shape": variant_shape,
            }
        )
    return parsed


def _build_fasta_index(path: Path, *, accession: str) -> dict[str, int]:
    """Build a minimal, samtools-``.fai``-equivalent random-access index
    for a single-accession reference FASTA by scanning its header and
    first sequence line: ``offset`` (byte offset where sequence data
    begins), ``linebases`` (sequence characters per line) and
    ``linewidth`` (bytes per line, including the newline)."""
    with open(path, "rb") as handle:
        header_line = handle.readline()
        if not header_line.startswith(b">"):
            raise ReferenceIntegrityError(f"reference FASTA {path} does not start with a '>' header line")
        header_id = header_line[1:].split()[0].decode("ascii", errors="replace") if header_line[1:].split() else ""
        if header_id != accession:
            raise ReferenceIntegrityError(
                f"reference FASTA {path} header {header_id!r} does not match expected accession "
                f"{accession!r}"
            )
        offset = handle.tell()
        first_seq_line = handle.readline()
        if not first_seq_line:
            raise ReferenceIntegrityError(f"reference FASTA {path} has no sequence data after its header")
        linewidth = len(first_seq_line)
        linebases = len(first_seq_line.rstrip(b"\r\n"))
        if linebases <= 0:
            raise ReferenceIntegrityError(f"reference FASTA {path} first sequence line is empty")
    return {"offset": offset, "linebases": linebases, "linewidth": linewidth}


def _read_fasta_bases(path: Path, index: dict[str, int], *, position: int, length: int) -> str:
    if length <= 0:
        return ""
    linebases = index["linebases"]
    linewidth = index["linewidth"]
    offset = index["offset"]
    line_number, line_offset = divmod(position, linebases)
    byte_offset = offset + line_number * linewidth + line_offset
    lines_spanned = ((line_offset + length - 1) // linebases) + 1
    read_len = lines_spanned * linewidth
    with open(path, "rb") as handle:
        handle.seek(byte_offset)
        raw = handle.read(read_len)
    bases = raw.translate(None, b"\r\n").decode("ascii", errors="replace").upper()
    if len(bases) < length:
        raise ReferenceIntegrityError(
            f"reference FASTA {path} does not contain {length} base(s) at 0-based position "
            f"{position} (sequence exhausted)"
        )
    return bases[:length]


def _make_default_fasta_deleted_allele_checker(
    *, reference_fasta_path: Path, genomic_accession: str
) -> Callable[..., str]:
    """Build the DEFAULT ``fasta_deleted_allele_checker`` used when a
    caller (the real operator) does not inject one: a small, dependency-
    free FASTA random-access reader (no pysam requirement) built once per
    run from the already-checksum-verified reference FASTA."""
    index = _build_fasta_index(reference_fasta_path, accession=genomic_accession)

    def checker(*, accession: str, position: int, deleted_sequence: str) -> str:
        if accession != genomic_accession:
            raise ReferenceIntegrityError(
                f"FASTA checker only supports the pinned accession {genomic_accession!r}, got "
                f"{accession!r}"
            )
        return _read_fasta_bases(reference_fasta_path, index, position=position, length=len(deleted_sequence))

    return checker


#: Exception-type -> retry-policy category name (spec
#: ``rate_limits_retries.retry_policy.retryable_transport``). Checked in
#: this order since ``TimeoutError``/``ConnectionError`` are themselves
#: ``OSError`` subclasses and ``ssl.SSLError`` is also an ``OSError``
#: subclass on most platforms -- the most specific applicable category
#: always wins.
def _classify_transport_exception(exc: BaseException) -> str:
    """Classify a RAISED transport exception into one of this package's
    fixed retry-policy categories: ``"timeout"``, ``"tls_error"``,
    ``"connection_error"``, or ``"other"`` (anything else, including a
    malformed-shape/structural failure, which is never retried regardless
    of ``retryable_transport``'s contents). This is a pure exception-TYPE
    classification -- it never inspects or echoes the exception's own
    message, which may carry a secret/signed value."""
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, ssl.SSLError):
        return "tls_error"
    if isinstance(exc, ConnectionError):
        return "connection_error"
    return "other"


def _perform_step_request(
    *,
    url: str,
    transport: Callable[[str], dict[str, Any]],
    retry_policy: dict[str, Any],
    sleep: Callable[[float], None],
    min_interval_seconds: float,
    random_uniform: Callable[[float, float], float] = random.uniform,
) -> dict[str, Any]:
    """Perform one projector HTTP GET (step1 or step2) with rate-limiting
    and retry, ALWAYS via the injected ``transport``/``sleep`` callables
    (never a real socket call or a real ``time.sleep``), and ALWAYS via the
    injected ``random_uniform(low, high)`` seam for full-jitter backoff
    (never the real ``random`` module's nondeterministic state in a test).
    Returns ``{"outcome": "success"|"failure", ...typed transport fields
    for the terminal attempt..., "elapsed_ms", "retry_exhausted": bool,
    "attempts": list[dict]}`` where ``attempts`` carries ONE record per
    HTTP round-trip actually made (``attempt`` 1-based, ``requested_url``,
    ``final_url``, ``http_status``, ``media_type``, ``body``,
    ``byte_length``, ``sha256``, ``elapsed_ms``, ``retry_category``,
    ``terminal``, ``retry_exhausted``) -- every attempt is preserved, not
    only the terminal one, so a retried-then-succeeded request's full
    history remains auditable. ``endpoint.ProjectorEndpointSecurityError``
    (an allowlist/binding violation) is NEVER caught here -- it always
    propagates and aborts the whole run, on ANY attempt.

    Full-jitter backoff: ``random_uniform(0, min(backoff_base * 2**(attempt-1),
    backoff_cap))``. When ``retry_policy["honor_retry_after_header"]`` is
    true and a retryable HTTP response carries a numeric ``Retry-After``
    response header, the actual sleep before the next attempt is
    ``max(jitter_backoff, retry_after_seconds)`` -- the server's requested
    wait is always honored, never shortened by jitter."""
    max_attempts = max(1, int(retry_policy.get("max_attempts_per_request", 1)))
    retryable_http = set(retry_policy.get("retryable_http", []))
    retryable_transport_categories = set(retry_policy.get("retryable_transport", []))
    backoff_base = float(retry_policy.get("backoff_base_seconds", 2.0))
    backoff_cap = float(retry_policy.get("backoff_cap_seconds", 60.0))
    honor_retry_after = bool(retry_policy.get("honor_retry_after_header", False))

    attempts: list[dict[str, Any]] = []

    def _backoff_sleep(*, attempt: int, retry_after_seconds: float | None) -> None:
        jitter_ceiling = min(backoff_base * (2 ** (attempt - 1)), backoff_cap)
        backoff_seconds = random_uniform(0.0, jitter_ceiling)
        if honor_retry_after and retry_after_seconds is not None:
            backoff_seconds = max(backoff_seconds, retry_after_seconds)
        sleep(backoff_seconds)

    def _extract_retry_after(response_headers: dict[str, str] | None) -> float | None:
        if not response_headers:
            return None
        raw_value = response_headers.get("Retry-After", response_headers.get("retry-after"))
        if raw_value is None:
            return None
        try:
            return float(raw_value)
        except (TypeError, ValueError):
            return None

    for attempt in range(1, max_attempts + 1):
        sleep(min_interval_seconds)
        start = time.perf_counter()
        try:
            validated = fetch_raw_with_transport(requested_url=url, transport=transport)
        except ProjectorTransportValidationError as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            category = _classify_transport_exception(exc.__cause__) if exc.__cause__ is not None else "other"
            is_retryable = category in retryable_transport_categories
            is_last_attempt = attempt >= max_attempts
            terminal = (not is_retryable) or is_last_attempt
            attempts.append(
                {
                    "attempt": attempt,
                    "requested_url": url,
                    "final_url": None,
                    "http_status": None,
                    "media_type": None,
                    "body": None,
                    "byte_length": None,
                    "sha256": None,
                    "elapsed_ms": elapsed_ms,
                    "retry_category": category,
                    "terminal": terminal,
                    "retry_exhausted": terminal and is_retryable,
                }
            )
            if is_retryable and not is_last_attempt:
                _backoff_sleep(attempt=attempt, retry_after_seconds=None)
                continue
            return {
                "outcome": "failure",
                "error_detail": f"transport failure: {type(exc).__name__} (category={category})",
                "final_url": None,
                "http_status": None,
                "body_sha256": None,
                "elapsed_ms": elapsed_ms,
                "retry_exhausted": terminal and is_retryable,
                "attempts": attempts,
            }

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        # A binding/allowlist violation is a run-abort condition, never a
        # per-row failure -- this is intentionally NOT inside the
        # ProjectorTransportValidationError except-clause above, and is
        # never retried.
        assert_allowed_projector_final_url(requested_url=url, final_url=validated["final_url"])

        http_status = validated["http_status"]
        if http_status == 200:
            attempts.append(
                {
                    "attempt": attempt,
                    "requested_url": url,
                    "final_url": validated["final_url"],
                    "http_status": http_status,
                    "media_type": validated["media_type"],
                    "body": validated["body"],
                    "byte_length": validated["byte_length"],
                    "sha256": validated["sha256"],
                    "elapsed_ms": elapsed_ms,
                    "retry_category": "success",
                    "terminal": True,
                    "retry_exhausted": False,
                }
            )
            return {
                "outcome": "success",
                **validated,
                "elapsed_ms": elapsed_ms,
                "retry_exhausted": False,
                "attempts": attempts,
            }

        is_retryable = http_status in retryable_http
        is_last_attempt = attempt >= max_attempts
        terminal = (not is_retryable) or is_last_attempt
        attempts.append(
            {
                "attempt": attempt,
                "requested_url": url,
                "final_url": validated["final_url"],
                "http_status": http_status,
                "media_type": validated["media_type"],
                "body": validated["body"],
                "byte_length": validated["byte_length"],
                "sha256": validated["sha256"],
                "elapsed_ms": elapsed_ms,
                "retry_category": "retryable_http" if is_retryable else "non_retryable_http",
                "terminal": terminal,
                "retry_exhausted": terminal and is_retryable,
            }
        )
        if is_retryable and not is_last_attempt:
            retry_after_seconds = _extract_retry_after(validated.get("response_headers"))
            _backoff_sleep(attempt=attempt, retry_after_seconds=retry_after_seconds)
            continue
        return {
            "outcome": "failure",
            "error_detail": f"http_status={http_status}",
            "final_url": validated["final_url"],
            "http_status": http_status,
            "body_sha256": validated["sha256"],
            "elapsed_ms": elapsed_ms,
            "retry_exhausted": terminal and is_retryable,
            "attempts": attempts,
        }

    # Unreachable in practice (the loop always returns), but keeps a safe
    # fallback shape if max_attempts somehow permitted zero iterations.
    return {
        "outcome": "failure",
        "error_detail": "no attempt made",
        "final_url": None,
        "http_status": None,
        "body_sha256": None,
        "elapsed_ms": 0,
        "retry_exhausted": False,
        "attempts": attempts,
    }


def project_clipe_rows(
    *,
    source_id: str,
    scores_csv_bytes: bytes,
    expected_header: list[str],
    expected_rows: int,
    expected_scores_sha256: str,
    expected_scores_byte_length: int,
    transcript: str,
    genomic_accession: str,
    assembly: str,
    reference_fasta_path: Path | str,
    expected_reference_sha256: str,
    transport: Callable[[str], dict[str, Any]],
    min_interval_seconds: float,
    retry_policy: dict[str, Any],
    sleep: Callable[[float], None],
    fasta_deleted_allele_checker: Callable[..., str] | None = None,
    random_uniform: Callable[[float, float], float] = random.uniform,
) -> dict[str, Any]:
    """Project every row of the frozen cliPE scores CSV from
    ``transcript`` c.HGVS to a canonical ``genomic_accession`` SPDI via the
    exact step1 (contextuals) -> step2 (canonical_representative) NCBI
    Variation Services sequence, over the injected ``transport``. The
    pinned reference FASTA checksum is verified FIRST -- before the scores
    CSV is even parsed, and before any request is issued (spec
    ``fasta_validation.precondition``). Returns ``{"mapping_rows":
    list[dict], "request_index": list[dict], "raw_attempt_envelopes":
    list[dict], "status_counts": dict[str, int], "shape_counts": dict[str,
    int], "retry_exhausted_rows": list[int], "retry_exhausted_count":
    int}``. ``request_index``/``raw_attempt_envelopes`` are ATTEMPT-level
    (one entry per HTTP round-trip actually made, including every retried-
    then-abandoned attempt) -- ``raw_attempt_envelopes`` additionally
    preserves the actual response ``body`` bytes for every attempt so the
    operator can publish a raw file per attempt without needing to replay/
    re-derive them from the transport. A row's ``mapping_rows`` entry's
    ``step1_body_sha256``/``step2_body_sha256`` always reflect the
    TERMINAL (successful) body for that step, never an earlier failed
    retry's body. ``retry_exhausted_rows`` lists the ``source_row`` of
    every row where some step's retry budget was genuinely exhausted on a
    retryable status/category (never a row that failed immediately on a
    non-retryable status). Raises ``ReferenceIntegrityError`` or
    ``FrozenInputError`` before any transport call on an input-integrity
    failure; raises ``endpoint.ProjectorEndpointSecurityError`` (never
    caught) the instant any binding/allowlist violation is observed,
    aborting the whole run immediately."""
    validate_reference_fasta_checksum(
        reference_fasta_path=reference_fasta_path, expected_sha256=expected_reference_sha256
    )

    csv_text = scores_csv_bytes.decode("utf-8")
    parsed_rows = validate_frozen_scores_input(
        csv_text=csv_text,
        expected_header=expected_header,
        expected_rows=expected_rows,
        expected_sha256=expected_scores_sha256,
        expected_byte_length=expected_scores_byte_length,
        transcript=transcript,
    )

    if fasta_deleted_allele_checker is None:
        fasta_deleted_allele_checker = _make_default_fasta_deleted_allele_checker(
            reference_fasta_path=Path(reference_fasta_path), genomic_accession=genomic_accession
        )

    mapping_rows: list[dict[str, Any]] = []
    request_index: list[dict[str, Any]] = []
    raw_attempt_envelopes: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    shape_counts: dict[str, int] = {}
    retry_exhausted_rows: list[int] = []

    def _perform(*, url: str) -> dict[str, Any]:
        return _perform_step_request(
            url=url,
            transport=transport,
            retry_policy=retry_policy,
            sleep=sleep,
            min_interval_seconds=min_interval_seconds,
            random_uniform=random_uniform,
        )

    def _record_attempts(*, source_row: int, step: str, outcome: dict[str, Any]) -> None:
        for attempt in outcome.get("attempts", []):
            request_index.append(
                {
                    "source_row": source_row,
                    "step": step,
                    "attempt": attempt["attempt"],
                    "requested_url": attempt["requested_url"],
                    "final_url": attempt["final_url"],
                    "http_status": attempt["http_status"],
                    "body_sha256": attempt["sha256"],
                    "elapsed_ms": attempt["elapsed_ms"],
                    "retry_category": attempt["retry_category"],
                    "terminal": attempt["terminal"],
                    "retry_exhausted": attempt["retry_exhausted"],
                }
            )
            raw_attempt_envelopes.append(
                {
                    "source_row": source_row,
                    "step": step,
                    "attempt": attempt["attempt"],
                    "requested_url": attempt["requested_url"],
                    "final_url": attempt["final_url"],
                    "http_status": attempt["http_status"],
                    "media_type": attempt["media_type"],
                    "body": attempt["body"],
                    "body_sha256": attempt["sha256"],
                    "elapsed_ms": attempt["elapsed_ms"],
                }
            )

    def _finalize_row(row_fields: dict[str, Any]) -> None:
        built = ClipeCdnaSpdiMappingRow(**row_fields).to_dict()
        mapping_rows.append(built)
        status_counts[built["status"]] = status_counts.get(built["status"], 0) + 1
        shape_counts[built["variant_shape"]] = shape_counts.get(built["variant_shape"], 0) + 1

    for record in parsed_rows:
        source_row = record["source_row"]
        source_record_id = record["accession"]
        variant_shape = record["variant_shape"]
        hgvs_c = record["hgvs_c"]
        hgvs_nt_source = record["hgvs_nt"]

        base_row_fields: dict[str, Any] = {
            "source_id": source_id,
            "source_row": source_row,
            "source_record_id": source_record_id,
            "gene": GENE,
            "transcript": transcript,
            "hgvs_c": hgvs_c,
            "hgvs_nt_source": hgvs_nt_source,
            "variant_shape": variant_shape,
        }

        # --- step1: hgvs contextuals -------------------------------------------------
        step1_url = build_step1_hgvs_contextuals_url(hgvs_c=hgvs_c)
        step1_outcome = _perform(url=step1_url)
        _record_attempts(source_row=source_row, step="step1", outcome=step1_outcome)
        row_retry_exhausted = bool(step1_outcome.get("retry_exhausted"))

        if step1_outcome["outcome"] != "success":
            if row_retry_exhausted:
                retry_exhausted_rows.append(source_row)
            _finalize_row(
                {
                    **base_row_fields,
                    "tx_spdi": None,
                    "genomic_spdi": None,
                    "hgvs_g": None,
                    "assembly": None,
                    "genomic_accession": None,
                    "status": "STEP1_HTTP_ERROR",
                    "fasta_deleted_observed": None,
                    "error_detail": step1_outcome["error_detail"],
                    "step1_body_sha256": step1_outcome.get("body_sha256"),
                    "step2_body_sha256": None,
                }
            )
            continue

        step1_body_sha256 = step1_outcome["sha256"]
        try:
            tx_parsed = parse_step1_contextuals_response(
                body=step1_outcome["body"], media_type=step1_outcome["media_type"], expected_seq_id=transcript
            )
        except Step1SchemaError as exc:
            status = _STEP1_REASON_TO_STATUS.get(exc.reason, "STEP1_SCHEMA_VIOLATION")
            _finalize_row(
                {
                    **base_row_fields,
                    "tx_spdi": None,
                    "genomic_spdi": None,
                    "hgvs_g": None,
                    "assembly": None,
                    "genomic_accession": None,
                    "status": status,
                    "fasta_deleted_observed": None,
                    "error_detail": str(exc),
                    "step1_body_sha256": step1_body_sha256,
                    "step2_body_sha256": None,
                }
            )
            continue

        tx_spdi = tx_parsed["spdi"]

        # --- step2: spdi canonical_representative -------------------------------------
        step2_url = build_step2_spdi_canonical_representative_url(spdi=tx_spdi)
        step2_outcome = _perform(url=step2_url)
        _record_attempts(source_row=source_row, step="step2", outcome=step2_outcome)
        if step2_outcome.get("retry_exhausted"):
            row_retry_exhausted = True

        if step2_outcome["outcome"] != "success":
            if row_retry_exhausted:
                retry_exhausted_rows.append(source_row)
            _finalize_row(
                {
                    **base_row_fields,
                    "tx_spdi": None,
                    "genomic_spdi": None,
                    "hgvs_g": None,
                    "assembly": None,
                    "genomic_accession": None,
                    "status": "STEP2_HTTP_ERROR",
                    "fasta_deleted_observed": None,
                    "error_detail": step2_outcome["error_detail"],
                    "step1_body_sha256": step1_body_sha256,
                    "step2_body_sha256": step2_outcome.get("body_sha256"),
                }
            )
            continue

        step2_body_sha256 = step2_outcome["sha256"]
        try:
            genomic_parsed = parse_step2_canonical_representative_response(
                body=step2_outcome["body"], media_type=step2_outcome["media_type"], expected_seq_id=genomic_accession
            )
        except Step2SchemaError as exc:
            status = _STEP2_REASON_TO_STATUS.get(exc.reason, "STEP2_SCHEMA_VIOLATION")
            _finalize_row(
                {
                    **base_row_fields,
                    "tx_spdi": None,
                    "genomic_spdi": None,
                    "hgvs_g": None,
                    "assembly": None,
                    "genomic_accession": None,
                    "status": status,
                    "fasta_deleted_observed": None,
                    "error_detail": str(exc),
                    "step1_body_sha256": step1_body_sha256,
                    "step2_body_sha256": step2_body_sha256,
                }
            )
            continue

        genomic_spdi = genomic_parsed["spdi"]
        deleted_sequence = genomic_parsed["deleted_sequence"]

        # --- independent FASTA deleted-allele verification -----------------------------
        try:
            observed = fasta_deleted_allele_checker(
                accession=genomic_accession, position=genomic_parsed["position"], deleted_sequence=deleted_sequence
            )
        except ReferenceIntegrityError as exc:
            _finalize_row(
                {
                    **base_row_fields,
                    "tx_spdi": None,
                    "genomic_spdi": None,
                    "hgvs_g": None,
                    "assembly": None,
                    "genomic_accession": None,
                    "status": "FASTA_OUT_OF_RANGE",
                    "fasta_deleted_observed": None,
                    "error_detail": str(exc),
                    "step1_body_sha256": step1_body_sha256,
                    "step2_body_sha256": step2_body_sha256,
                }
            )
            continue

        if not all(ch in "ACGT" for ch in observed):
            _finalize_row(
                {
                    **base_row_fields,
                    "tx_spdi": None,
                    "genomic_spdi": None,
                    "hgvs_g": None,
                    "assembly": None,
                    "genomic_accession": None,
                    "status": "NON_ACGT_ALLELE",
                    "fasta_deleted_observed": None,
                    "error_detail": f"FASTA-observed allele {observed!r} contains non-ACGT bases",
                    "step1_body_sha256": step1_body_sha256,
                    "step2_body_sha256": step2_body_sha256,
                }
            )
            continue

        if observed != deleted_sequence:
            _finalize_row(
                {
                    **base_row_fields,
                    "tx_spdi": None,
                    "genomic_spdi": None,
                    "hgvs_g": None,
                    "assembly": None,
                    "genomic_accession": None,
                    "status": "FASTA_REF_MISMATCH",
                    "fasta_deleted_observed": None,
                    "error_detail": (
                        f"FASTA-observed allele {observed!r} does not match the canonical "
                        f"deleted_sequence {deleted_sequence!r}"
                    ),
                    "step1_body_sha256": step1_body_sha256,
                    "step2_body_sha256": step2_body_sha256,
                }
            )
            continue

        _finalize_row(
            {
                **base_row_fields,
                "tx_spdi": tx_spdi,
                "genomic_spdi": genomic_spdi,
                "hgvs_g": None,
                "assembly": assembly,
                "genomic_accession": genomic_accession,
                "status": "PROJECTED_FASTA_VERIFIED",
                "fasta_deleted_observed": observed,
                "error_detail": None,
                "step1_body_sha256": step1_body_sha256,
                "step2_body_sha256": step2_body_sha256,
            }
        )

    return {
        "mapping_rows": mapping_rows,
        "request_index": request_index,
        "raw_attempt_envelopes": raw_attempt_envelopes,
        "status_counts": status_counts,
        "shape_counts": shape_counts,
        "retry_exhausted_rows": retry_exhausted_rows,
        "retry_exhausted_count": len(retry_exhausted_rows),
    }


__all__ = [
    "ProjectorAcquisitionError",
    "FrozenInputError",
    "ReferenceIntegrityError",
    "validate_frozen_scores_input",
    "validate_frozen_source_bundle_manifest",
    "validate_reference_fasta_checksum",
    "project_clipe_rows",
]
