#!/usr/bin/env python
"""Fetch and verify the RAPTOR v2 TSC2 cliPE cDNA -> GRCh38 SPDI projector
acquisition (``docs/project/specs/raptor-v2-clipe-cdna-spdi-projector-acquisition-v1.yaml``).

This is the ONLY module in this slice that performs real network I/O --
``raptor.external.tsc2_cdna_projector`` is pure, deterministic parsing/
validation/hashing/manifest construction over an injected ``transport``
callable and an injected/reconstructed reference-FASTA seam (see that
package's module docstrings). This script:

1. Loads ``configs/external/tsc2_clipe_cdna_spdi_projector_v1.yaml`` (the
   frozen scores-CSV pins, the pinned NC_000016.10 reference FASTA, the
   identity pins, and the rate-limit/retry policy).
2. Reads the already-published TSC2 source-ingestion bundle's frozen
   ``mavedb_clipe`` scores CSV from ``--source-root`` (default
   ``$RAPTOR_TSC2_SOURCE_ROOT``), verifying every path stays inside that
   run directory and never follows a symlink.
3. Re-verifies the pinned reference FASTA's checksum and the scores CSV's
   header/row-count/hash BEFORE building any request plan (defense in
   depth -- ``ingest.project_clipe_rows`` re-verifies both again itself).
4. Runs the real, rate-limited, retrying two-step NCBI Variation Services
   sequence (the "hgvs contextuals" step, then the "spdi
   canonical_representative" step -- NEVER the unstable batch-contextuals
   endpoint and NEVER a direct hgvs-to-canonical path, which this API does
   not expose) through
   ``raptor.external.tsc2_cdna_projector.ingest.project_clipe_rows``,
   which independently grounds every accepted genomic SPDI's deleted
   allele against the pinned local FASTA before recording success.
5. Builds a bundle manifest + canonical mapping/request-index JSONL and
   publishes an external, create-only, hash-verified bundle via
   ``raptor.external.tsc2_cdna_projector.bundle.publish_projector_bundle``.
6. Optionally writes a compact, aggregate-only committed summary (counts,
   hashes, status/shape histograms -- never a per-row HGVS/SPDI string,
   raw NCBI response body, or any clinical/evidence-strength claim) to an
   EXPLICITLY supplied ``--summary-output`` path.

Rate limiting/retry (a minimum 1 request/second interval, exponential
backoff with a full-jitter-free cap, honoring ``retryable_http``/
``retryable_transport`` categories up to ``max_attempts_per_request``) is
driven entirely by ``project_clipe_rows``'s injected ``sleep``/
``retry_policy`` parameters -- this script only ever supplies the REAL
``time.sleep`` and the real HTTPS transport below; it never re-implements
the retry loop itself. If retryable failures exhaust their budget across
more than the configured fraction (default 0.05, i.e. 5%) of all rows,
this run is treated as unreliable and is reported as a failure rather than
silently publishing a partial/degraded bundle.

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

from raptor.external.tsc2_cdna_projector.bundle import (  # noqa: E402
    ProjectorBundleBoundaryError,
    ProjectorManifestError,
    build_committed_summary,
    build_projector_bundle_manifest,
    canonical_mapping_jsonl_bytes,
    canonical_request_index_jsonl_bytes,
    publish_projector_bundle,
)
from raptor.external.tsc2_cdna_projector.ingest import (  # noqa: E402
    FrozenInputError,
    ProjectorAcquisitionError,
    ReferenceIntegrityError,
    project_clipe_rows,
    validate_frozen_scores_input,
    validate_frozen_source_bundle_manifest,
    validate_reference_fasta_checksum,
)

SOURCE_ROOT_ENV = "RAPTOR_TSC2_SOURCE_ROOT"
REFERENCE_ROOT_ENV = "RAPTOR_TSC2_REFERENCE_ROOT"
OUTPUT_ROOT_ENV = "RAPTOR_TSC2_CDNA_PROJECTOR_ROOT"
DEFAULT_OUTPUT_ROOT = Path.home() / "raptor-data" / "external" / "tsc2-cdna-projector"
DEFAULT_CONFIG = REPO_ROOT / "configs" / "external" / "tsc2_clipe_cdna_spdi_projector_v1.yaml"
_USER_AGENT = "raptor-tsc2-clipe-cdna-spdi-projector/1.0 (+https://github.com/srinivasdrona/raptor)"


class ProjectorOperatorError(RuntimeError):
    """Base error for this operator CLI's own config/plan-building/path
    containment failures (never a library-domain error)."""


def _load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.is_file():
        raise ProjectorOperatorError(f"config file not found: {config_path}")
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ProjectorOperatorError(f"config {config_path} did not parse to a mapping")
    return loaded


def _assert_no_symlink_ancestor(path: Path, *, context: str) -> None:
    """Raise ``ProjectorOperatorError`` if ``path`` itself, or any of its
    ancestor directories, is a symlink/reparse point. Never follows a
    symlink to decide this -- ``Path.is_symlink`` inspects the link
    itself, never its target."""
    current = path
    while True:
        if current.is_symlink():
            raise ProjectorOperatorError(
                f"{context} path {path} has a symlink/reparse ancestor at {current}; refusing to "
                "read through a symlink"
            )
        parent = current.parent
        if parent == current:
            return
        current = parent


def _resolve_safe_path_in_run_dir(run_dir: Path, relative_path: Any, *, context: str) -> Path:
    """Resolve ``relative_path`` (a config-PINNED path, never a manifest-
    supplied one) against ``run_dir``, verifying containment and symlink-
    safety before any byte is read. Raises ``ProjectorOperatorError`` --
    and never reads any bytes -- on any violation."""
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ProjectorOperatorError(f"invalid pinned {context} relative_path: {relative_path!r}")
    candidate = run_dir / relative_path
    _assert_no_symlink_ancestor(candidate, context=f"pinned {context}")
    resolved_run_dir = run_dir.resolve()
    resolved_candidate = candidate.resolve()
    try:
        resolved_candidate.relative_to(resolved_run_dir)
    except ValueError as exc:
        raise ProjectorOperatorError(
            f"pinned {context} relative_path {relative_path!r} escapes the source run directory "
            f"{run_dir}"
        ) from exc
    if not candidate.is_file():
        raise ProjectorOperatorError(f"pinned {context} not found at {candidate}")
    return candidate


def _read_source_bundle_manifest(source_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    """Read the already-published TSC2 source-ingestion bundle's own
    ``bundle_manifest.json`` (config-pinned ``manifest_filename``) from
    ``source_root/source_bundle.run_name``, safely (symlink/containment-
    checked, same as the pinned scores CSV) -- this manifest is then
    handed to ``validate_frozen_source_bundle_manifest`` BEFORE the scores
    CSV bytes are read/used for anything."""
    source_bundle_cfg = config["inputs"]["source_bundle"]
    run_dir = source_root / source_bundle_cfg["run_name"]
    manifest_path = _resolve_safe_path_in_run_dir(
        run_dir, source_bundle_cfg["manifest_filename"], context="source_bundle_manifest"
    )
    try:
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProjectorOperatorError(f"source bundle manifest {manifest_path} is not valid JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ProjectorOperatorError(f"source bundle manifest {manifest_path} did not parse to a mapping")
    return loaded


def _resolve_pinned_scores_path(source_root: Path, config: dict[str, Any]) -> Path:
    """Resolve the frozen scores CSV's config-PINNED relative path
    (never a manifest-supplied one) against the published source bundle's
    run directory, verifying containment and symlink-safety before any
    byte is read."""
    source_bundle_cfg = config["inputs"]["source_bundle"]
    run_dir = source_root / source_bundle_cfg["run_name"]
    return _resolve_safe_path_in_run_dir(
        run_dir, source_bundle_cfg["scores_artifact"]["relative_path"], context="scores artifact"
    )


class _RateLimitedHttpsTransport:
    """Real HTTPS GET transport built on ``http.client``/``ssl`` (never
    ``urllib.request``/``requests``/``httpx``/``aiohttp``). Rate-limiting
    and retry are NOT implemented here -- they live entirely in
    ``project_clipe_rows``'s injected ``sleep``/``retry_policy``
    parameters; this callable is invoked once per attempt and simply
    performs one GET, returning the typed transport-result shape
    ``ingest``/``endpoint`` expect."""

    def __init__(self, *, connect_timeout: float, read_timeout: float) -> None:
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._ssl_context = ssl.create_default_context()

    def __call__(self, url: str) -> dict[str, Any]:
        parts = urlsplit(url)
        if parts.scheme != "https":
            raise ProjectorOperatorError(f"refusing to fetch a non-https URL: {url}")
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
            connection.request(
                "GET", path, headers={"Accept": "application/json", "User-Agent": _USER_AGENT}
            )
            response = connection.getresponse()
            body = response.read()
            status = response.status
            media_type = response.getheader("Content-Type") or "application/octet-stream"
            response_headers: dict[str, str] | None = None
            getheaders = getattr(response, "getheaders", None)
            if callable(getheaders):
                try:
                    response_headers = {str(key): str(value) for key, value in getheaders()}
                except Exception:  # noqa: BLE001 - header extraction is best-effort only
                    response_headers = None
        finally:
            connection.close()
        # NCBI Variation Services' fixed-resource GET endpoints used by this
        # slice are not expected to redirect; final_url is always the
        # requested_url itself (endpoint.assert_allowed_projector_final_url
        # still independently re-verifies this on every call).
        result: dict[str, Any] = {"final_url": url, "http_status": status, "media_type": media_type, "body": body}
        if response_headers is not None:
            result["response_headers"] = response_headers
        return result



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
        help=f"external projector bundle root (default: ${OUTPUT_ROOT_ENV} or {DEFAULT_OUTPUT_ROOT})",
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
                raise ProjectorOperatorError(f"no --source-root supplied and ${SOURCE_ROOT_ENV} is not set")
            source_root = Path(source_root_env)
        source_root = source_root.expanduser()

        if args.reference_root is not None:
            reference_root = args.reference_root
        else:
            reference_root_env = os.environ.get(REFERENCE_ROOT_ENV)
            if not reference_root_env or not reference_root_env.strip():
                raise ProjectorOperatorError(f"no --reference-root supplied and ${REFERENCE_ROOT_ENV} is not set")
            reference_root = Path(reference_root_env)
        reference_root = reference_root.expanduser()

        if args.output_root is not None:
            output_root = args.output_root
        else:
            output_root_env = os.environ.get(OUTPUT_ROOT_ENV)
            output_root = Path(output_root_env) if output_root_env and output_root_env.strip() else DEFAULT_OUTPUT_ROOT
        output_root = output_root.expanduser()

        identity_pins = config["inputs"]["identity_pins"]
        reference_cfg = config["inputs"]["genomic_reference"]
        scores_cfg = config["inputs"]["source_bundle"]["scores_artifact"]
        rate_limits_retries = config["rate_limits_retries"]
        retry_policy = rate_limits_retries["retry_policy"]
        # Fail fast on a malformed retry policy: every projector request
        # attempt is governed by these four pinned axes (spec
        # rate_limits_retries.retry_policy) -- a missing key here is a
        # configuration bug, never silently defaulted.
        for _required_retry_key in (
            "retryable_http", "retryable_transport", "non_retryable_http", "max_attempts_per_request",
        ):
            if _required_retry_key not in retry_policy:
                raise ProjectorOperatorError(
                    f"rate_limits_retries.retry_policy is missing required key {_required_retry_key!r}"
                )

        scores_path = _resolve_pinned_scores_path(source_root, config)
        source_bundle_cfg = config["inputs"]["source_bundle"]
        source_manifest = _read_source_bundle_manifest(source_root, config)
        # Re-verify the published source bundle's OWN manifest (recomputed
        # canonical content hash, bundle_id, and the exact/unique frozen
        # scores artifact identity) BEFORE the scores CSV bytes are read
        # for validation/use -- a tampered manifest or a decoy/duplicate
        # artifact_id is rejected here, never silently disambiguated.
        validate_frozen_source_bundle_manifest(
            source_manifest=source_manifest,
            expected_bundle_id=source_bundle_cfg["bundle_id"],
            expected_manifest_content_hash=source_bundle_cfg["manifest_content_hash"],
            expected_scores_artifact={
                "artifact_id": scores_cfg["artifact_id"],
                "source_id": "mavedb_clipe",
                "relative_path": scores_cfg["relative_path"],
                "sha256": scores_cfg["sha256"],
                "byte_length": scores_cfg["byte_length"],
            },
        )

        scores_csv_bytes = scores_path.read_bytes()
        reference_fasta_path = reference_root / reference_cfg["fasta_filename"]

        # Pre-flight, fail-fast verification (project_clipe_rows re-verifies
        # both again internally -- this is intentional defense in depth so
        # a misconfigured root/pin is reported clearly before any request
        # plan is even built).
        validate_reference_fasta_checksum(
            reference_fasta_path=reference_fasta_path, expected_sha256=reference_cfg["sha256"]
        )
        validate_frozen_scores_input(
            csv_text=scores_csv_bytes.decode("utf-8"),
            expected_header=list(scores_cfg["exact_header"]),
            expected_rows=int(scores_cfg["expected_rows"]),
            expected_sha256=scores_cfg["sha256"],
            expected_byte_length=int(scores_cfg["byte_length"]),
            transcript=identity_pins["transcript"],
        )

        min_interval_seconds = float(rate_limits_retries["min_interval_seconds"])
        timeout_seconds = rate_limits_retries.get("timeout_seconds", {})
        transport = _RateLimitedHttpsTransport(
            connect_timeout=float(timeout_seconds.get("connect", 10)),
            read_timeout=float(timeout_seconds.get("read", 45)),
        )

        started_at = time.monotonic()
        result = project_clipe_rows(
            source_id="mavedb_clipe",
            scores_csv_bytes=scores_csv_bytes,
            expected_header=list(scores_cfg["exact_header"]),
            expected_rows=int(scores_cfg["expected_rows"]),
            expected_scores_sha256=scores_cfg["sha256"],
            expected_scores_byte_length=int(scores_cfg["byte_length"]),
            transcript=identity_pins["transcript"],
            genomic_accession=identity_pins["genomic_accession"],
            assembly=identity_pins["assembly"],
            reference_fasta_path=reference_fasta_path,
            expected_reference_sha256=reference_cfg["sha256"],
            transport=transport,
            min_interval_seconds=min_interval_seconds,
            retry_policy=retry_policy,
            sleep=time.sleep,
        )
        wall_clock_seconds = time.monotonic() - started_at

        total_rows = int(scores_cfg["expected_rows"])
        # Repeated retryable HTTP/transport failures exhausting their retry
        # budget (retryable_http / retryable_transport, up to
        # max_attempts_per_request) on more than this fraction of all rows
        # means the run is unreliable and must be reported as a failure
        # rather than silently published as a partial/degraded bundle (spec
        # rate_limits_retries.row_failure_vs_run_abort.run_abort). This
        # threshold uses ONLY project_clipe_rows's own retry_exhausted_count
        # aggregate -- never a status-vocabulary rollup -- since a row can
        # fail permanently on a non-retryable status without ever having
        # exhausted a retry budget at all.
        max_retry_exhaustion_rate = float(
            rate_limits_retries.get("run_abort", {}).get("max_retry_exhaustion_rate", 0.05)
        )
        retry_exhausted_count = int(result["retry_exhausted_count"])
        if total_rows > 0 and (retry_exhausted_count / total_rows) > max_retry_exhaustion_rate:
            raise ProjectorAcquisitionError(
                f"{retry_exhausted_count}/{total_rows} rows exhausted their retry budget on a "
                f"retryable status/category ({retry_exhausted_count / total_rows:.1%}), exceeding "
                f"the {max_retry_exhaustion_rate:.0%} run-abort threshold; refusing to publish an "
                "unreliable partial bundle"
            )

        mapping_rows = result["mapping_rows"]
        request_index = result["request_index"]
        mapping_payload = canonical_mapping_jsonl_bytes(mapping_rows)
        request_index_payload = canonical_request_index_jsonl_bytes(request_index)

        output_cfg = config["outputs"]["external_bundle"]
        artifact_cfg = output_cfg["artifacts"]
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Every raw response file is built directly from project_clipe_rows's
        # own attempt-level envelopes (never reconstructed by replaying a
        # transport-capturing wrapper) -- one deterministic file per
        # attempt actually made, including every retried-then-abandoned one.
        raw_payloads: dict[str, bytes] = {}
        raw_artifacts: list[dict[str, Any]] = []
        _step_suffix = {"step1": "contextuals", "step2": "canonical_representative", "step3": "hgvs"}
        for raw_attempt in result["raw_attempt_envelopes"]:
            step = raw_attempt["step"]
            source_row = raw_attempt["source_row"]
            attempt = raw_attempt["attempt"]
            body = raw_attempt.get("body")
            if body is None:
                continue
            relative_path = f"raw/{step}/{source_row:04d}-attempt-{attempt:02d}-{_step_suffix.get(step, step)}.json"
            raw_payloads[relative_path] = body
            raw_artifacts.append(
                {
                    "artifact_id": f"raw-{step}-{source_row:04d}-attempt-{attempt:02d}",
                    "relative_path": relative_path,
                    "byte_length": len(body),
                    "sha256": raw_attempt["body_sha256"],
                    "row_count": 1,
                }
            )

        artifacts = [
            {
                "artifact_id": "mapping-jsonl",
                "relative_path": artifact_cfg["mapping_jsonl"]["relative_path"],
                "byte_length": len(mapping_payload),
                "sha256": hashlib.sha256(mapping_payload).hexdigest(),
                "row_count": len(mapping_rows),
            },
            {
                "artifact_id": "request-index-jsonl",
                "relative_path": artifact_cfg["request_log"]["relative_path"],
                "byte_length": len(request_index_payload),
                "sha256": hashlib.sha256(request_index_payload).hexdigest(),
                "row_count": len(request_index),
            },
            *raw_artifacts,
        ]

        shape_counts = result["shape_counts"]
        status_counts = result["status_counts"]
        success_count = status_counts.get("PROJECTED_FASTA_VERIFIED", 0)
        failure_count = len(mapping_rows) - success_count

        manifest = build_projector_bundle_manifest(
            bundle_id=output_cfg["bundle_id"],
            created_at=created_at,
            input_scores={
                "artifact_id": scores_cfg["artifact_id"],
                "sha256": scores_cfg["sha256"],
                "byte_length": scores_cfg["byte_length"],
                "row_count": scores_cfg["expected_rows"],
            },
            reference={"accession": reference_cfg["accession"], "sha256": reference_cfg["sha256"]},
            endpoint_pins={
                "base_url": config["api"]["base_url"],
                "step_sequence": list(config["api"]["step_sequence"]),
                "min_interval_seconds": min_interval_seconds,
            },
            artifacts=artifacts,
            status_counts=status_counts,
            shape_counts=shape_counts,
            success_count=success_count,
            failure_count=failure_count,
            boundaries={
                "network": "operator_only",
                "clinical_use": "forbidden",
                "evidence_strength_use": "forbidden",
            },
            request_budget_observed={
                "step1": sum(1 for entry in request_index if entry["step"] == "step1"),
                "step2": sum(1 for entry in request_index if entry["step"] == "step2"),
                "wall_clock_seconds": round(wall_clock_seconds, 1),
            },
        )

        publish_result = publish_projector_bundle(
            repo_root=REPO_ROOT,
            output_root=output_root,
            run_name=output_cfg["run_name"],
            manifest=manifest,
            mapping_payload=mapping_payload,
            request_index_payload=request_index_payload,
            raw_payloads=raw_payloads,
        )
    except ProjectorOperatorError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except (ReferenceIntegrityError, FrozenInputError) as exc:
        print(f"ERROR: input integrity failure ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
    except ProjectorAcquisitionError as exc:
        print(f"ERROR: acquisition failure ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
    except (ProjectorBundleBoundaryError, ProjectorManifestError) as exc:
        print(f"ERROR: bundle publication failure ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1

    print(f"projector bundle written: {publish_result['run_dir']}")
    print(
        f"rows={len(mapping_rows)} success={success_count} failure={failure_count} "
        f"content_hash={manifest['content_hash']}"
    )

    if args.summary_output is not None:
        summary = build_committed_summary(manifest)
        args.summary_output.parent.mkdir(parents=True, exist_ok=True)
        args.summary_output.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"summary written: {args.summary_output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
