"""MaveDB score-set metadata + scores.csv verification for the TSC2 cliPE
functional-dataset source (``urn:mavedb:00001201-a-1``).

``verify_scoreset`` is the single entry point: given an already-fetched
score-set metadata JSON document and an already-fetched raw scores CSV
(``accession,hgvs_nt,hgvs_splice,hgvs_pro,score``), it independently
observes the target gene (``targetGenes[].name``), the target RefSeq
transcript (``methodText``, reusing
``raptor.external.mave.metadata.extract_observed_transcript``'s regex), the
license (the structured ``license`` object, reusing
``raptor.external.mave.metadata.extract_observed_license``), the declared
variant count (``numVariants``) and the CSV's own data-row count, and the
scores CSV's sha256 -- then fails loud on ANY drift against the
caller-supplied expected pins. This module performs no network I/O; both
documents are injected as already-fetched bytes/text.

``assert_allowed_mavedb_final_url`` is the MaveDB-specific counterpart of
``raptor.external.tsc2_sources.endpoint.assert_allowed_final_url`` (which is
scoped to literature sources only, per its own module docstring): it
restricts both the requested and the (possibly redirected) final URL to
HTTPS ``api.mavedb.org`` score-set endpoints, so the real operator can
validate a transport's reported ``final_url`` before this module ever
parses its body.
"""
from __future__ import annotations

import csv
import hashlib
import io
from typing import Any
from urllib.parse import urlsplit

from raptor.external.mave.metadata import (
    ScoreSetMetadataError,
    extract_observed_license,
    extract_observed_transcript,
    parse_score_set_metadata,
)

MAVEDB_ALLOWED_HOST = "api.mavedb.org"
MAVEDB_ALLOWED_PATH_PREFIX = "/api/v1/score-sets/"


class MaveSourceVerificationError(ValueError):
    """Raised when MaveDB score-set metadata/scores cannot be parsed, or any
    observed value (gene, transcript, license, variant count, scores.csv
    sha256) drifts from its caller-supplied expected pin."""


def _extract_gene_name(metadata: dict[str, Any]) -> str:
    target_genes = metadata.get("targetGenes")
    if not isinstance(target_genes, list) or not target_genes:
        raise MaveSourceVerificationError(
            "mavedb score-set metadata is missing a non-empty 'targetGenes' list"
        )
    names: list[str] = []
    for entry in target_genes:
        name = entry.get("name") if isinstance(entry, dict) else None
        if not name:
            raise MaveSourceVerificationError(
                f"mavedb score-set metadata targetGenes entry is malformed: {entry!r}"
            )
        names.append(name)
    distinct = sorted(set(names))
    if len(distinct) != 1:
        raise MaveSourceVerificationError(
            f"mavedb score-set metadata targetGenes names more than one distinct target "
            f"gene {distinct!r} -- refusing to pick one as the observed gene"
        )
    return distinct[0]


def _extract_variant_count(metadata: dict[str, Any]) -> int:
    num_variants = metadata.get("numVariants")
    if not isinstance(num_variants, int) or isinstance(num_variants, bool):
        raise MaveSourceVerificationError(
            f"mavedb score-set metadata numVariants is missing or malformed: {num_variants!r}"
        )
    return num_variants


def _count_score_rows(scores_csv_bytes: bytes) -> int:
    try:
        text = scores_csv_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MaveSourceVerificationError(f"mavedb scores.csv is not valid UTF-8: {exc}") from exc
    rows = [row for row in csv.reader(io.StringIO(text)) if row]
    if not rows:
        raise MaveSourceVerificationError("mavedb scores.csv is empty (no header row)")
    return len(rows) - 1


def verify_scoreset(
    *,
    metadata_json: str,
    scores_csv_bytes: bytes,
    expected_gene: str,
    expected_transcript: str,
    expected_variant_count: int,
    expected_license: str,
    expected_sha256: str,
) -> dict[str, Any]:
    """Independently verify a MaveDB score-set metadata document and its raw
    scores CSV against caller-supplied expected pins. Returns
    ``{"gene", "transcript", "license", "variant_count", "sha256",
    "lifecycle_state": "STAGED_VERIFIED"}`` on success. Raises
    ``MaveSourceVerificationError`` on ANY parse failure or drift -- never
    silently accepts a mismatch."""
    try:
        metadata = parse_score_set_metadata(metadata_json)
    except ScoreSetMetadataError as exc:
        raise MaveSourceVerificationError(
            f"mavedb score-set metadata could not be parsed: {exc}"
        ) from exc

    gene = _extract_gene_name(metadata)
    if gene != expected_gene:
        raise MaveSourceVerificationError(
            f"mavedb target gene mismatch: expected {expected_gene!r}, observed {gene!r}"
        )

    try:
        transcript = extract_observed_transcript(metadata)
    except ScoreSetMetadataError as exc:
        raise MaveSourceVerificationError(
            f"mavedb transcript could not be observed from methodText: {exc}"
        ) from exc
    if transcript != expected_transcript:
        raise MaveSourceVerificationError(
            f"mavedb transcript mismatch: expected {expected_transcript!r}, observed {transcript!r}"
        )

    try:
        license_id = extract_observed_license(metadata)
    except ScoreSetMetadataError as exc:
        raise MaveSourceVerificationError(
            f"mavedb license could not be observed from the license object: {exc}"
        ) from exc
    if license_id != expected_license:
        raise MaveSourceVerificationError(
            f"mavedb license mismatch: expected {expected_license!r}, observed {license_id!r}"
        )

    declared_variant_count = _extract_variant_count(metadata)
    if declared_variant_count != expected_variant_count:
        raise MaveSourceVerificationError(
            f"mavedb metadata variant_count mismatch: expected {expected_variant_count!r}, "
            f"observed numVariants={declared_variant_count!r}"
        )

    observed_row_count = _count_score_rows(scores_csv_bytes)
    if observed_row_count != expected_variant_count:
        raise MaveSourceVerificationError(
            f"mavedb scores.csv variant row count mismatch: expected {expected_variant_count!r}, "
            f"observed {observed_row_count!r} data rows"
        )

    observed_sha256 = hashlib.sha256(scores_csv_bytes).hexdigest()
    if observed_sha256.lower() != expected_sha256.lower():
        raise MaveSourceVerificationError(
            f"mavedb scores.csv sha256 hash mismatch: expected {expected_sha256!r}, "
            f"observed {observed_sha256!r}"
        )

    return {
        "gene": gene,
        "transcript": transcript,
        "license": license_id,
        "variant_count": declared_variant_count,
        "sha256": observed_sha256,
        "lifecycle_state": "STAGED_VERIFIED",
    }


def assert_allowed_mavedb_final_url(*, requested_url: str, final_url: str) -> None:
    """Validate both the requested and the (possibly redirected) final URL
    against the fixed HTTPS ``api.mavedb.org`` score-set endpoint allowlist.
    Mirrors ``endpoint.assert_allowed_final_url``'s intent for the
    literature sources, scoped to MaveDB instead."""
    for label, url in (("requested_url", requested_url), ("final_url", final_url)):
        parts = urlsplit(url)
        if parts.scheme != "https":
            raise MaveSourceVerificationError(
                f"mavedb {label} scheme is not in the HTTPS allowlist: {parts.scheme!r} ({url!r})"
            )
        if parts.netloc != MAVEDB_ALLOWED_HOST:
            raise MaveSourceVerificationError(
                f"mavedb {label} host is not the allowed {MAVEDB_ALLOWED_HOST!r} host: {url!r}"
            )
        if not parts.path.startswith(MAVEDB_ALLOWED_PATH_PREFIX):
            raise MaveSourceVerificationError(
                f"mavedb {label} path is not under the allowed {MAVEDB_ALLOWED_PATH_PREFIX!r} "
                f"prefix: {url!r}"
            )


__all__ = [
    "MaveSourceVerificationError",
    "MAVEDB_ALLOWED_HOST",
    "MAVEDB_ALLOWED_PATH_PREFIX",
    "verify_scoreset",
    "assert_allowed_mavedb_final_url",
]