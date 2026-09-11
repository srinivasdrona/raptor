#!/usr/bin/env python
"""Fetch and verify the RAPTOR v2 TSC2 VAMP-seq protein -> genomic SPDI
crosswalk acquisition
(``docs/project/specs/raptor-v2-vamp-genomic-crosswalk-acquisition-v1.yaml``).

This is the ONLY module in this slice that performs real network I/O --
``raptor.external.tsc2_vamp_crosswalk`` is pure, deterministic parsing/
validation/hashing/manifest construction over an injected ``transport``
callable, injected archive/score bytes, an injected/reconstructed
reference-FASTA seam, and an injected genomic normalizer (see that
package's module docstrings). This script:

1. Loads ``configs/external/tsc2_vamp_genomic_crosswalk_v1.yaml`` (the
   frozen VAMP-seq score-artifact pins, the pinned Zenodo TSC2-analysis-V1
   archive/member pins, the pinned ``NC_000016.10`` reference FASTA, and
   the archive/score table contracts).
2. Reads the already-published TSC2 source-ingestion bundle's own
   ``bundle_manifest.json`` and its frozen ``igvf_vamp_seq`` score TSV
   from ``--source-root`` (default ``$RAPTOR_TSC2_SOURCE_ROOT``), safely
   (symlink/containment-checked), and re-verifies the manifest's own
   canonical content hash and the pinned score artifact's identity BEFORE
   any network call.
3. Downloads the immutable Zenodo archive (record 20837254, filename
   ``FowlerLab/TSC2_analysis-V1.zip``) via a real, rate-limited, retrying
   HTTPS GET, then re-verifies the downloaded bytes and extracts/verifies
   its two required GMM identity-table members.
4. Builds the deterministic protein -> genomic SPDI crosswalk for every
   frozen score row through
   ``raptor.external.tsc2_vamp_crosswalk.ingest.build_vamp_genomic_crosswalk``,
   instantiating ``raptor.ingest.normalizer.SeqRepoGenomicNormalizer``
   against the pinned reference FASTA root.
5. Builds a bundle manifest + canonical crosswalk JSONL and publishes an
   external, create-only, hash-verified bundle via
   ``raptor.external.tsc2_vamp_crosswalk.bundle.publish_vamp_crosswalk_bundle``.
6. Optionally writes a compact, aggregate-only committed summary (counts,
   hashes, status histograms, the archive's public DOI/hash metadata, and
   the fixed PacBio no-go decision -- never a per-row protein variant,
   hgvs_c string, genomic SPDI, score, or functional class) to an
   EXPLICITLY supplied ``--summary-output`` path.

This slice NEVER downloads, imports, references, or constructs a path to
either of the two PacBio raw-read files: NO_GO -- the immutable archive
already carries a complete, frozen protein/transcript/genomic identity
crosswalk, and those large raw-read files are unnecessary for this bounded
identity slice.

This script deliberately does NOT import ``urllib.request``, ``requests``,
``httpx`` or ``aiohttp`` (this repository's fixed forbidden-network-import
allowlist for this slice) -- the real HTTPS GET below is built directly on
the standard library's lower-level ``http.client``/``ssl`` modules.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import ssl
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from raptor.external.tsc2_sources.bundle import compute_bundle_content_hash  # noqa: E402
from raptor.external.tsc2_vamp_crosswalk.archive import (  # noqa: E402
    ArchiveValidationError,
    validate_zenodo_archive_and_extract_members,
)
from raptor.external.tsc2_vamp_crosswalk.bundle import (  # noqa: E402
    VampCrosswalkBundleBoundaryError,
    VampCrosswalkManifestError,
    build_committed_summary,
    build_crosswalk_bundle_manifest,
    canonical_crosswalk_jsonl_bytes,
    publish_vamp_crosswalk_bundle,
)
from raptor.external.tsc2_vamp_crosswalk.endpoint import (  # noqa: E402
    VampCrosswalkEndpointSecurityError,
    VampCrosswalkTransportValidationError,
    assert_allowed_zenodo_final_url,
    build_zenodo_archive_download_url,
    fetch_with_transport,
)
from raptor.external.tsc2_vamp_crosswalk.ingest import (  # noqa: E402
    CrosswalkNormalizationError,
    FrozenInputError,
    ReferenceIntegrityError,
    VampCrosswalkIngestError,
    build_vamp_genomic_crosswalk,
    validate_reference_fasta_checksum,
)
from raptor.external.tsc2_vamp_crosswalk.model import CrosswalkContractError  # noqa: E402
from raptor.ingest.normalizer import (  # noqa: E402
    ReferenceChecksumMismatchError,
    ReferenceNotAvailableError,
    SeqRepoGenomicNormalizer,
)

SOURCE_ROOT_ENV = "RAPTOR_TSC2_SOURCE_ROOT"
REFERENCE_ROOT_ENV = "RAPTOR_TSC2_REFERENCE_ROOT"
OUTPUT_ROOT_ENV = "RAPTOR_TSC2_VAMP_CROSSWALK_ROOT"
DEFAULT_OUTPUT_ROOT = Path.home() / "raptor-data" / "external" / "tsc2-vamp-crosswalk"
DEFAULT_CONFIG = REPO_ROOT / "configs" / "external" / "tsc2_vamp_genomic_crosswalk_v1.yaml"
_USER_AGENT = "raptor-tsc2-vamp-genomic-crosswalk/1.0 (+https://github.com/srinivasdrona/raptor)"


class VampCrosswalkOperatorError(RuntimeError):
    """Base error for this operator CLI's own config/plan-building/path
    containment failures (never a library-domain error)."""


class _NormalizerConfig:
    """Minimal ``config`` object ``SeqRepoGenomicNormalizer.normalize``
    expects: ``reference_checksums`` (accession -> pinned sha256,
    re-verified by the normalizer on every call) and a ``pins_dict()``
    used only to annotate any manual-queue item it emits."""

    def __init__(self, *, reference_checksums: dict[str, str], pins: dict[str, Any], run_id: str) -> None:
        self.reference_checksums = reference_checksums
        self._pins = pins
        self.run_id = run_id

    def pins_dict(self) -> dict[str, Any]:
        return dict(self._pins)


def _load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.is_file():
        raise VampCrosswalkOperatorError(f"config file not found: {config_path}")
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise VampCrosswalkOperatorError(f"config {config_path} did not parse to a mapping")
    return loaded


def _assert_no_symlink_ancestor(path: Path, *, context: str) -> None:
    """Raise ``VampCrosswalkOperatorError`` if ``path`` itself, or any of
    its ancestor directories, is a symlink/reparse point. Never follows a
    symlink to decide this -- ``Path.is_symlink`` inspects the link
    itself, never its target."""
    current = path
    while True:
        if current.is_symlink():
            raise VampCrosswalkOperatorError(
                f"{context} path {path} has a symlink/reparse ancestor at {current}; refusing to read "
                "through a symlink"
            )
        parent = current.parent
        if parent == current:
            return
        current = parent


def _resolve_safe_path_in_run_dir(run_dir: Path, relative_path: Any, *, context: str) -> Path:
    """Resolve ``relative_path`` (a config-PINNED path, never a manifest-
    supplied one) against ``run_dir``, verifying containment and symlink-
    safety before any byte is read."""
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise VampCrosswalkOperatorError(f"invalid pinned {context} relative_path: {relative_path!r}")
    candidate = run_dir / relative_path
    _assert_no_symlink_ancestor(candidate, context=f"pinned {context}")
    resolved_run_dir = run_dir.resolve()
    resolved_candidate = candidate.resolve()
    try:
        resolved_candidate.relative_to(resolved_run_dir)
    except ValueError as exc:
        raise VampCrosswalkOperatorError(
            f"pinned {context} relative_path {relative_path!r} escapes the source run directory {run_dir}"
        ) from exc
    if not candidate.is_file():
        raise VampCrosswalkOperatorError(f"pinned {context} not found at {candidate}")
    return candidate


def _read_source_bundle_manifest(source_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    """Read the already-published TSC2 source-ingestion bundle's own
    ``bundle_manifest.json`` (config-pinned ``manifest_filename``),
    safely (symlink/containment-checked)."""
    source_cfg = config["inputs"]["frozen_vamp_scores"]
    run_dir = source_root / source_cfg["run_name"]
    manifest_path = _resolve_safe_path_in_run_dir(run_dir, source_cfg["manifest_filename"], context="source_bundle_manifest")
    try:
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise VampCrosswalkOperatorError(f"source bundle manifest {manifest_path} is not valid JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise VampCrosswalkOperatorError(f"source bundle manifest {manifest_path} did not parse to a mapping")
    return loaded


def _validate_source_bundle_manifest_pin(source_manifest: dict[str, Any], config: dict[str, Any]) -> None:
    """Re-verify the published source bundle manifest's OWN recomputed
    canonical content hash (reusing ``tsc2_sources.bundle.
    compute_bundle_content_hash`` -- never a reimplementation) against
    both its own recorded value (self-consistency) and this slice's
    pinned expectation, and confirm the pinned VAMP score artifact's
    identity fields are present and exact -- all BEFORE any network call
    or archive download."""
    source_cfg = config["inputs"]["frozen_vamp_scores"]
    recomputed = compute_bundle_content_hash(source_manifest)
    recorded = source_manifest.get("content_hash")
    if recomputed != recorded:
        raise VampCrosswalkOperatorError(
            f"source bundle manifest content_hash is not internally consistent: recorded {recorded!r} "
            f"!= recomputed {recomputed!r}"
        )
    if recomputed != source_cfg["source_manifest_content_hash"]:
        raise VampCrosswalkOperatorError(
            f"source bundle manifest content_hash does not match the pinned expectation: "
            f"{recomputed!r} != {source_cfg['source_manifest_content_hash']!r}"
        )
    if source_manifest.get("bundle_id") != source_cfg["source_bundle_id"]:
        raise VampCrosswalkOperatorError(
            f"source bundle manifest bundle_id {source_manifest.get('bundle_id')!r} does not match "
            f"the pinned expectation {source_cfg['source_bundle_id']!r}"
        )
    artifacts = source_manifest.get("artifacts", [])
    matches = [a for a in artifacts if isinstance(a, dict) and a.get("artifact_id") == source_cfg["artifact_id"]]
    if len(matches) != 1:
        raise VampCrosswalkOperatorError(
            f"source bundle manifest must contain exactly one artifact with artifact_id "
            f"{source_cfg['artifact_id']!r}, found {len(matches)}"
        )
    artifact = matches[0]
    for field_name in ("relative_path", "sha256", "byte_length"):
        if artifact.get(field_name) != source_cfg[field_name]:
            raise VampCrosswalkOperatorError(
                f"source bundle manifest artifact {source_cfg['artifact_id']!r} field {field_name!r} "
                f"does not match the pinned expectation: {artifact.get(field_name)!r} != "
                f"{source_cfg[field_name]!r}"
            )


class _RateLimitedHttpsTransport:
    """Real HTTPS GET transport built on ``http.client``/``ssl`` (never
    ``urllib.request``/``requests``/``httpx``/``aiohttp``). Retries a
    retryable HTTP status (``retryable_http``) up to
    ``max_attempts_per_request`` with exponential backoff, sleeping via
    the REAL ``time.sleep`` -- this is the ONLY place a real socket call
    or a real sleep ever occurs; ``endpoint.fetch_with_transport`` itself
    still independently re-verifies the final (successful-or-not) result
    shape/status."""

    def __init__(
        self,
        *,
        connect_timeout: float,
        read_timeout: float,
        min_interval_seconds: float,
        retryable_http: set[int],
        max_attempts_per_request: int,
        backoff_base_seconds: float,
        backoff_cap_seconds: float,
    ) -> None:
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._min_interval_seconds = min_interval_seconds
        self._retryable_http = retryable_http
        self._max_attempts_per_request = max_attempts_per_request
        self._backoff_base_seconds = backoff_base_seconds
        self._backoff_cap_seconds = backoff_cap_seconds
        self._ssl_context = ssl.create_default_context()

    def _one_attempt(self, url: str) -> dict[str, Any]:
        parts = urlsplit(url)
        if parts.scheme != "https":
            raise VampCrosswalkOperatorError(f"refusing to fetch a non-https URL: {url}")
        connection = http.client.HTTPSConnection(
            parts.netloc, timeout=self._connect_timeout, context=self._ssl_context
        )
        try:
            # Establish the connection explicitly (rather than letting the
            # first .request() call do it implicitly) so the READ timeout
            # can be applied to the connected socket separately from the
            # CONNECT timeout passed to the constructor above.
            connection.connect()
            connection.sock.settimeout(self._read_timeout)
            path = parts.path + (f"?{parts.query}" if parts.query else "")
            # Zenodo's file-download endpoint 406s on a narrow media-type
            # Accept header (e.g. "application/zip") -- only the universal
            # wildcard is guaranteed to succeed for this archive.
            connection.request("GET", path, headers={"Accept": "*/*", "User-Agent": _USER_AGENT})
            response = connection.getresponse()
            body = response.read()
            status = response.status
            media_type = response.getheader("Content-Type") or "application/octet-stream"
        finally:
            connection.close()
        return {"final_url": url, "http_status": status, "media_type": media_type, "body": body}

    def __call__(self, url: str) -> dict[str, Any]:
        last_result: dict[str, Any] | None = None
        for attempt in range(1, self._max_attempts_per_request + 1):
            time.sleep(self._min_interval_seconds)
            last_result = self._one_attempt(url)
            if last_result["http_status"] == 200 or last_result["http_status"] not in self._retryable_http:
                return last_result
            if attempt < self._max_attempts_per_request:
                backoff = min(self._backoff_base_seconds * (2 ** (attempt - 1)), self._backoff_cap_seconds)
                time.sleep(backoff)
        return last_result


def _validate_expected_pilot_result(*, manifest: dict[str, Any], expected_pilot: dict[str, Any]) -> None:
    """Fail-closed gate: the crosswalk manifest's actual totals must match
    the frozen ``expected_pilot`` pins EXACTLY before publication. Every
    axis is derived from the manifest itself (never from any other,
    possibly stale, source): ``total_score_rows`` from
    ``input_scores.row_count``, ``archive_crosswalk_rows`` from
    ``status_counts`` (every status EXCEPT ``ARCHIVE_CROSSWALK_ABSENT``),
    ``status_counts``/``verified_unique_spdi`` directly, and
    ``conservation`` from ``input_scores.row_count``/``counts.rows`` (a
    duplicate source_row is structurally impossible given this package's
    one-row-per-score-row contract, so ``duplicate_source_rows`` is always
    compared against the derived constant ``0``). Raises
    ``VampCrosswalkOperatorError`` naming the specific mismatched axis
    (``total_score_rows``, ``archive_crosswalk_rows``, ``status_counts``,
    ``verified_unique_spdi`` or ``conservation``)."""
    actual_total_score_rows = manifest["input_scores"]["row_count"]
    if actual_total_score_rows != expected_pilot["total_score_rows"]:
        raise VampCrosswalkOperatorError(
            f"expected_pilot gate failed on total_score_rows: manifest input_scores.row_count "
            f"{actual_total_score_rows!r} != expected {expected_pilot['total_score_rows']!r}"
        )

    status_counts = manifest["status_counts"]
    actual_archive_crosswalk_rows = sum(status_counts.values()) - status_counts.get("ARCHIVE_CROSSWALK_ABSENT", 0)
    if actual_archive_crosswalk_rows != expected_pilot["archive_crosswalk_rows"]:
        raise VampCrosswalkOperatorError(
            f"expected_pilot gate failed on archive_crosswalk_rows: derived "
            f"{actual_archive_crosswalk_rows!r} (status_counts sum minus ARCHIVE_CROSSWALK_ABSENT) != "
            f"expected {expected_pilot['archive_crosswalk_rows']!r}"
        )

    if status_counts != expected_pilot["status_counts"]:
        raise VampCrosswalkOperatorError(
            f"expected_pilot gate failed on status_counts: manifest {status_counts!r} != expected "
            f"{expected_pilot['status_counts']!r}"
        )

    actual_verified_unique_spdi = manifest["verified_unique_spdi"]
    if actual_verified_unique_spdi != expected_pilot["verified_unique_spdi"]:
        raise VampCrosswalkOperatorError(
            f"expected_pilot gate failed on verified_unique_spdi: manifest "
            f"{actual_verified_unique_spdi!r} != expected {expected_pilot['verified_unique_spdi']!r}"
        )

    actual_output_crosswalk_rows = manifest["counts"]["rows"]
    actual_conservation = {
        "input_score_rows": actual_total_score_rows,
        "output_crosswalk_rows": actual_output_crosswalk_rows,
        "dropped_rows": actual_total_score_rows - actual_output_crosswalk_rows,
        "duplicate_source_rows": 0,
    }
    if actual_conservation != expected_pilot["conservation"]:
        raise VampCrosswalkOperatorError(
            f"expected_pilot gate failed on conservation: derived {actual_conservation!r} != expected "
            f"{expected_pilot['conservation']!r}"
        )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help=f"config YAML (default: {DEFAULT_CONFIG})")
    parser.add_argument(
        "--source-root", type=Path, default=None,
        help=f"published TSC2 source-ingestion bundle root (default: ${SOURCE_ROOT_ENV})",
    )
    parser.add_argument(
        "--reference-root", type=Path, default=None,
        help=f"pinned genomic reference FASTA root (default: ${REFERENCE_ROOT_ENV})",
    )
    parser.add_argument(
        "--output-root", type=Path, default=None,
        help=f"external crosswalk bundle root (default: ${OUTPUT_ROOT_ENV} or {DEFAULT_OUTPUT_ROOT})",
    )
    parser.add_argument(
        "--summary-output", type=Path, default=None,
        help="optional path to write the aggregate-only committed summary JSON; never written unless supplied",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    try:
        config = _load_config(args.config)

        if args.source_root is not None:
            source_root = args.source_root
        else:
            source_root_env = os.environ.get(SOURCE_ROOT_ENV)
            if not source_root_env or not source_root_env.strip():
                raise VampCrosswalkOperatorError(f"no --source-root supplied and ${SOURCE_ROOT_ENV} is not set")
            source_root = Path(source_root_env)
        source_root = source_root.expanduser()

        if args.reference_root is not None:
            reference_root = args.reference_root
        else:
            reference_root_env = os.environ.get(REFERENCE_ROOT_ENV)
            if not reference_root_env or not reference_root_env.strip():
                raise VampCrosswalkOperatorError(f"no --reference-root supplied and ${REFERENCE_ROOT_ENV} is not set")
            reference_root = Path(reference_root_env)
        reference_root = reference_root.expanduser()

        if args.output_root is not None:
            output_root = args.output_root
        else:
            output_root_env = os.environ.get(OUTPUT_ROOT_ENV)
            output_root = Path(output_root_env) if output_root_env and output_root_env.strip() else DEFAULT_OUTPUT_ROOT
        output_root = output_root.expanduser()

        source_cfg = config["inputs"]["frozen_vamp_scores"]
        archive_cfg = config["inputs"]["zenodo_archive"]
        reference_cfg = config["inputs"]["genomic_reference"]
        identity_pins = config["inputs"]["identity_pins"]
        archive_table_cfg = config["archive_table_contract"]
        rate_limits_retries = config["rate_limits_retries"]
        retry_policy = rate_limits_retries["retry_policy"]
        for required_key in ("retryable_http", "non_retryable_http", "max_attempts_per_request"):
            if required_key not in retry_policy:
                raise VampCrosswalkOperatorError(f"rate_limits_retries.retry_policy is missing required key {required_key!r}")

        # Read + verify the pinned source bundle manifest and score
        # artifact bytes BEFORE any network call is made.
        run_dir = source_root / source_cfg["run_name"]
        source_manifest = _read_source_bundle_manifest(source_root, config)
        _validate_source_bundle_manifest_pin(source_manifest, config)
        scores_path = _resolve_safe_path_in_run_dir(run_dir, source_cfg["relative_path"], context="vamp score artifact")
        score_tsv_gz_bytes = scores_path.read_bytes()

        reference_fasta_path = reference_root / reference_cfg["fasta_filename"]
        # Pre-flight, fail-fast reference verification (build_vamp_genomic_
        # crosswalk re-verifies this again internally -- intentional
        # defense in depth so a misconfigured root/pin is reported clearly
        # before any archive download is attempted).
        validate_reference_fasta_checksum(reference_fasta_path=reference_fasta_path, expected_sha256=reference_cfg["sha256"])

        min_interval_seconds = float(rate_limits_retries["min_interval_seconds"])
        timeout_seconds = rate_limits_retries.get("timeout_seconds", {})
        transport = _RateLimitedHttpsTransport(
            connect_timeout=float(timeout_seconds.get("connect", 10)),
            read_timeout=float(timeout_seconds.get("read", 120)),
            min_interval_seconds=min_interval_seconds,
            retryable_http=set(retry_policy["retryable_http"]),
            max_attempts_per_request=int(retry_policy["max_attempts_per_request"]),
            backoff_base_seconds=float(retry_policy.get("backoff_base_seconds", 2.0)),
            backoff_cap_seconds=float(retry_policy.get("backoff_cap_seconds", 60.0)),
        )

        archive_url = build_zenodo_archive_download_url(record_id=archive_cfg["record_id"], filename=archive_cfg["filename"])
        fetched = fetch_with_transport(requested_url=archive_url, transport=transport)
        assert_allowed_zenodo_final_url(requested_url=archive_url, final_url=fetched["final_url"])
        archive_zip_bytes = fetched["body"]

        required_members = archive_cfg["required_members"]
        expected_archive = {
            "record_id": archive_cfg["record_id"],
            "filename": archive_cfg["filename"],
            "download_url": archive_cfg["download_url"],
            "byte_length": archive_cfg["byte_length"],
            "md5": archive_cfg["md5"],
            "sha256": archive_cfg["sha256"],
        }
        # Pre-flight re-verification (build_vamp_genomic_crosswalk redoes
        # this again internally over the same raw bytes).
        validate_zenodo_archive_and_extract_members(
            archive_bytes=archive_zip_bytes, expected_archive=expected_archive, required_members=required_members
        )

        normalizer = SeqRepoGenomicNormalizer(reference_root=reference_root)
        normalizer_config = _NormalizerConfig(
            reference_checksums={reference_cfg["accession"]: reference_cfg["sha256"]},
            pins=dict(identity_pins),
            run_id=config["outputs"]["external_bundle"]["bundle_id"],
        )

        result = build_vamp_genomic_crosswalk(
            source_id="igvf_vamp_seq",
            score_tsv_gz_bytes=score_tsv_gz_bytes,
            archive_zip_bytes=archive_zip_bytes,
            score_pins={
                "sha256": source_cfg["sha256"],
                "md5": source_cfg["md5"],
                "byte_length": source_cfg["byte_length"],
                "row_count": source_cfg["row_count"],
                "protein_accession": source_cfg["protein_accession"],
            },
            archive_pins={**expected_archive, "required_members": required_members},
            reference_fasta_path=reference_fasta_path,
            expected_reference_sha256=reference_cfg["sha256"],
            required_columns=list(archive_table_cfg["required_columns"]),
            required_values=dict(archive_table_cfg["required_values"]),
            transcript=identity_pins["transcript"],
            genomic_accession=identity_pins["genomic_accession"],
            assembly=identity_pins["assembly"],
            normalizer=normalizer,
            normalizer_config=normalizer_config,
        )

        crosswalk_rows = result["crosswalk_rows"]
        status_counts = result["status_counts"]
        crosswalk_payload = canonical_crosswalk_jsonl_bytes(crosswalk_rows)

        output_cfg = config["outputs"]["external_bundle"]
        artifact_cfg = output_cfg["artifacts"]
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        artifacts = [
            {
                "artifact_id": "raw-archive",
                "relative_path": artifact_cfg["raw_archive"]["relative_path"],
                "byte_length": len(archive_zip_bytes),
                "sha256": hashlib.sha256(archive_zip_bytes).hexdigest(),
                "row_count": 0,
            },
            {
                "artifact_id": "crosswalk-jsonl",
                "relative_path": artifact_cfg["crosswalk_jsonl"]["relative_path"],
                "byte_length": len(crosswalk_payload),
                "sha256": hashlib.sha256(crosswalk_payload).hexdigest(),
                "row_count": len(crosswalk_rows),
            },
        ]

        verified_unique_spdi = len(
            {row["genomic_spdi"] for row in crosswalk_rows if row["status"] == "CROSSWALK_SPDI_VERIFIED"}
        )
        follow_on_unresolved = {
            status: count
            for status, count in status_counts.items()
            if status != "CROSSWALK_SPDI_VERIFIED"
        }

        manifest = build_crosswalk_bundle_manifest(
            bundle_id=output_cfg["bundle_id"],
            created_at=created_at,
            input_scores={
                "artifact_id": source_cfg["artifact_id"],
                "sha256": source_cfg["sha256"],
                "md5": source_cfg["md5"],
                "byte_length": source_cfg["byte_length"],
                "row_count": source_cfg["row_count"],
            },
            archive={
                "record_id": archive_cfg["record_id"],
                "doi": archive_cfg["doi"],
                "filename": archive_cfg["filename"],
                "sha256": archive_cfg["sha256"],
                "md5": archive_cfg["md5"],
                "byte_length": archive_cfg["byte_length"],
            },
            reference={"accession": reference_cfg["accession"], "sha256": reference_cfg["sha256"]},
            artifacts=artifacts,
            counts={"rows": len(crosswalk_rows), "status_rows": len(crosswalk_rows)},
            status_counts=status_counts,
            boundaries={"network": "operator_only", "clinical_use": "forbidden", "evidence_strength_use": "forbidden"},
            verified_unique_spdi=verified_unique_spdi,
            follow_on_unresolved=follow_on_unresolved,
            pacbio_download_decision="NO_GO",
        )

        _validate_expected_pilot_result(manifest=manifest, expected_pilot=config["expected_pilot"])

        publish_result = publish_vamp_crosswalk_bundle(
            repo_root=REPO_ROOT,
            output_root=output_root,
            run_name=output_cfg["run_name"],
            manifest=manifest,
            crosswalk_payload=crosswalk_payload,
            archive_payload=archive_zip_bytes,
        )
    except VampCrosswalkOperatorError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except (ReferenceIntegrityError, ReferenceNotAvailableError, ReferenceChecksumMismatchError, FrozenInputError) as exc:
        print(f"ERROR: input integrity failure ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
    except (VampCrosswalkEndpointSecurityError, VampCrosswalkTransportValidationError) as exc:
        print(f"ERROR: network boundary failure ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
    except (ArchiveValidationError, CrosswalkNormalizationError, CrosswalkContractError, VampCrosswalkIngestError) as exc:
        print(f"ERROR: crosswalk build failure ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
    except (VampCrosswalkBundleBoundaryError, VampCrosswalkManifestError) as exc:
        print(f"ERROR: bundle publication failure ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1

    print(f"vamp crosswalk bundle written: {publish_result['run_dir']}")
    print(f"rows={len(crosswalk_rows)} status_counts={status_counts} content_hash={manifest['content_hash']}")

    if args.summary_output is not None:
        summary = build_committed_summary(manifest)
        args.summary_output.parent.mkdir(parents=True, exist_ok=True)
        args.summary_output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"summary written: {args.summary_output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
