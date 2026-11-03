#!/usr/bin/env python
"""Fetch and verify the RAPTOR v2 TSC2 missense source-ingestion pilot bundle
(``docs/project/specs/raptor-v2-missense-source-ingestion-v1.yaml``).

This is the ONLY module in this slice that performs real network I/O --
``raptor.external.tsc2_sources`` is pure, deterministic parsing/validation/
hashing/manifest construction over injected bytes (see that package's
module docstrings). This script:

1. Loads ``configs/external/tsc2_source_ingestion_v1.yaml`` (six sources:
   PubMed ESearch+EFetch, LitVar2 gene mapping, a configured Europe PMC JATS
   XML endpoint, the existing MaveDB cliPE score-set metadata/scores, and
   the IGVF VAMP-seq/SGE analysis-set/tabular-file/download endpoints).
2. Builds a source-kind-specific request plan using the already-committed
   literature endpoint builders (``endpoint.build_pubmed_esearch_url`` /
   ``build_litvar2_gene_url``) plus the configured MaveDB/IGVF URLs.
3. Runs a real, rate-limited ``urllib.request``-based transport (capturing
   the requested URL, the final URL after any redirect, HTTP status, media
   type and raw bytes) through ``raptor.external.tsc2_sources.ingest.
   run_ingestion``, which validates every final URL, verifies every
   artifact, and publishes an external, create-only, hash-verified bundle.
4. Optionally writes a compact, aggregate-only pilot summary (counts,
   hashes, source states -- never full text or per-variant rows) to an
   EXPLICITLY supplied ``--summary-output`` path; there is no default
   summary path, so nothing is ever written inside the repository unless a
   caller opts in.

NCBI Entrez/LitVar2 calls are rate-limited to at least 0.34s apart (the
documented safe interval without an API key). An optional ``--ncbi-api-key``
/``--ncbi-email`` (or ``NCBI_API_KEY``/``NCBI_EMAIL`` environment variable)
is attached ONLY to the PubMed ESearch and LitVar2 gene-search requests this
script itself builds, and is REDACTED before any URL is logged or persisted
into an artifact record (``ingest._sanitize_url``); this script never prints
a raw request/final URL itself.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from raptor.external.tsc2_sources.bundle import (  # noqa: E402
    BundleBoundaryError,
    BundleHashMismatchError,
    StatusVocabularyError,
    build_pilot_summary,
)
from raptor.external.tsc2_sources.endpoint import (  # noqa: E402
    build_litvar2_gene_url,
    build_pubmed_esearch_url,
)
from raptor.external.tsc2_sources.ingest import (  # noqa: E402
    SourceIngestionError,
    run_ingestion,
)

EXTERNAL_ROOT_ENV = "RAPTOR_TSC2_SOURCE_ROOT"
DEFAULT_EXTERNAL_ROOT = Path.home() / "raptor-data" / "external" / "tsc2-sources"
DEFAULT_CONFIG = REPO_ROOT / "configs" / "external" / "tsc2_source_ingestion_v1.yaml"
DEFAULT_MIN_NCBI_INTERVAL_SECONDS = 0.34
NCBI_RATE_LIMITED_HOSTS = frozenset({"eutils.ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov"})
_REQUEST_TIMEOUT_SECONDS = 30.0
_USER_AGENT = "raptor-tsc2-source-ingestion/1.0 (+https://github.com/srinivasdrona/raptor)"


class Tsc2OperatorError(RuntimeError):
    """Base error for the TSC2 source-bundle operator CLI."""


def resolve_external_root(config: dict[str, Any]) -> Path:
    env_name = config.get("output", {}).get("environment_variable", EXTERNAL_ROOT_ENV)
    return Path(os.environ.get(env_name) or DEFAULT_EXTERNAL_ROOT).expanduser()


def _append_query_params(url: str, extra: dict[str, str]) -> str:
    if not extra:
        return url
    parts = urlsplit(url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    pairs.extend(extra.items())
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment))


class _RateLimiter:
    """Enforces a minimum interval between successive requests to the same
    host (keyed by ``netloc``); hosts with no configured interval are never
    throttled."""

    def __init__(self, min_interval_by_host: dict[str, float]) -> None:
        self._min_interval_by_host = min_interval_by_host
        self._last_request_at: dict[str, float] = {}

    def wait(self, host: str) -> None:
        min_interval = self._min_interval_by_host.get(host)
        if min_interval is None:
            return
        now = time.monotonic()
        last = self._last_request_at.get(host)
        if last is not None:
            remaining = min_interval - (now - last)
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at[host] = time.monotonic()


def _make_transport(rate_limiter: _RateLimiter) -> Callable[[str], dict[str, Any]]:
    def transport(url: str) -> dict[str, Any]:
        rate_limiter.wait(urlsplit(url).netloc)
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read()
            final_url = response.geturl()
            status = getattr(response, "status", None) or response.getcode()
            media_type = response.headers.get_content_type()
        return {
            "final_url": final_url,
            "http_status": status,
            "media_type": media_type,
            "body": body,
        }

    return transport


def _build_plan(
    config: dict[str, Any],
    *,
    bundle_id: str,
    created_at: str,
    ncbi_api_key: str | None,
    ncbi_email: str | None,
) -> dict[str, Any]:
    try:
        gene = config["gene"]
        sources_cfg = config["sources"]
    except KeyError as exc:
        raise Tsc2OperatorError(f"config is missing required top-level key: {exc}") from exc
    ncbi_extra = {}
    if ncbi_api_key:
        ncbi_extra["api_key"] = ncbi_api_key
    if ncbi_email:
        ncbi_extra["email"] = ncbi_email

    try:
        pubmed_cfg = sources_cfg["pubmed"]
        esearch_url = build_pubmed_esearch_url(
            query=pubmed_cfg["query"],
            date_start=pubmed_cfg["publication_date_start"],
            date_end=pubmed_cfg["publication_date_end"],
            retmax=int(pubmed_cfg["retmax"]),
        )
        pubmed_plan = {
            "source_id": pubmed_cfg["source_id"],
            "source_kind": "pubmed",
            "request_url": _append_query_params(esearch_url, ncbi_extra),
            "required_pmid": str(pubmed_cfg["required_pmid"]),
        }

        litvar2_cfg = sources_cfg["litvar2"]
        litvar2_plan = {
            "source_id": litvar2_cfg["source_id"],
            "source_kind": "litvar2",
            "request_url": _append_query_params(
                build_litvar2_gene_url(gene=litvar2_cfg["gene"]), ncbi_extra,
            ),
            "gene": litvar2_cfg["gene"],
        }

        pmc_cfg = sources_cfg["pmc"]
        pmc_plan = {
            "source_id": pmc_cfg["source_id"],
            "source_kind": "pmc",
            "request_url": pmc_cfg["fulltext_endpoint"],
            "expected_pmcid": pmc_cfg["expected_pmcid"],
        }

        mave_cfg = sources_cfg["mavedb_clipe"]
        mavedb_plan = {
            "source_id": mave_cfg["source_id"],
            "source_kind": "mavedb",
            "metadata_request_url": mave_cfg["metadata_endpoint"],
            "scores_request_url": mave_cfg["scores_endpoint"],
            "expected_gene": mave_cfg["expected_gene"],
            "expected_transcript": mave_cfg["expected_transcript"],
            "expected_variant_count": int(mave_cfg["expected_variant_count"]),
            "expected_license": mave_cfg["expected_license"],
            "expected_sha256": mave_cfg["expected_sha256"],
            "expected_urn": mave_cfg["urn"],
            "urn": mave_cfg["urn"],
        }

        igvf_plans = []
        for key in ("igvf_vamp_seq", "igvf_sge"):
            igvf_cfg = sources_cfg[key]
            file_accession = igvf_cfg["file_accession"]
            igvf_plans.append(
                {
                    "source_id": igvf_cfg["source_id"],
                    "source_kind": "igvf",
                    "analysis_request_url": igvf_cfg["analysis_endpoint"],
                    "file_request_url": igvf_cfg["file_endpoint"],
                    "download_request_url": igvf_cfg["download_endpoint"],
                    "expected": {
                        "analysis_set": igvf_cfg["analysis_set"],
                        "file_accession": file_accession,
                        "required_status": igvf_cfg["required_status"],
                        "required_controlled_access": bool(igvf_cfg["required_controlled_access"]),
                        "expected_assembly": igvf_cfg["expected_assembly"],
                        "expected_file_size": int(igvf_cfg["expected_file_size"]),
                        "expected_md5": igvf_cfg["expected_md5"],
                        "expected_href": f"/tabular-files/{file_accession}/@@download/{file_accession}.tsv.gz",
                    },
                }
            )
    except KeyError as exc:
        raise Tsc2OperatorError(f"config is missing a required source field: {exc}") from exc

    return {
        "bundle_id": bundle_id,
        "created_at": created_at,
        "query": {"gene": gene},
        "sources": [pubmed_plan, litvar2_plan, pmc_plan, mavedb_plan, *igvf_plans],
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG,
        help=f"TSC2 source-ingestion YAML config (default: {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--output-root", type=Path, default=None,
        help="external run root (default: $RAPTOR_TSC2_SOURCE_ROOT or ~/raptor-data/external/tsc2-sources)",
    )
    parser.add_argument(
        "--run-name", default=None,
        help="external run directory name (default: config run_name)",
    )
    parser.add_argument(
        "--summary-output", type=Path, default=None,
        help=(
            "optional path to write the aggregate-only pilot summary JSON "
            "(e.g. data/census/tsc2_source_ingestion_pilot_2026-09-09.json); "
            "never written unless explicitly supplied"
        ),
    )
    parser.add_argument(
        "--ncbi-api-key", default=os.environ.get("NCBI_API_KEY"),
        help="optional NCBI Entrez api_key (never logged; default: $NCBI_API_KEY)",
    )
    parser.add_argument(
        "--ncbi-email", default=os.environ.get("NCBI_EMAIL"),
        help="optional NCBI Entrez contact email (never logged; default: $NCBI_EMAIL)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    if not args.config.is_file():
        print(f"ERROR: config file not found: {args.config}", file=sys.stderr)
        return 1
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        print(f"ERROR: config {args.config} did not parse to a mapping", file=sys.stderr)
        return 1

    try:
        output_root = args.output_root or resolve_external_root(config)
        run_name = args.run_name or config["run_name"]
        bundle_id = config["bundle_id"]
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        plan = _build_plan(
            config,
            bundle_id=bundle_id,
            created_at=created_at,
            ncbi_api_key=args.ncbi_api_key,
            ncbi_email=args.ncbi_email,
        )
    except (KeyError, Tsc2OperatorError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    min_interval = float(
        config.get("rate_limits", {}).get(
            "ncbi_without_api_key_min_interval_seconds", DEFAULT_MIN_NCBI_INTERVAL_SECONDS,
        )
    )
    rate_limiter = _RateLimiter({host: min_interval for host in NCBI_RATE_LIMITED_HOSTS})
    transport = _make_transport(rate_limiter)

    try:
        result = run_ingestion(
            plan=plan,
            transport=transport,
            repo_root=REPO_ROOT,
            output_root=output_root,
            run_name=run_name,
        )
    except SourceIngestionError as exc:
        print(
            f"ERROR: source ingestion failed for source_id={exc.source_id!r} "
            f"invariant={exc.invariant!r}: {exc}",
            file=sys.stderr,
        )
        return 1
    except (BundleBoundaryError, BundleHashMismatchError, StatusVocabularyError) as exc:
        # Bundle-manifest/publication-boundary domain errors (e.g. a
        # create-only/symlink-safety violation, an artifact hash mismatch,
        # or forbidden status vocabulary) never carry a URL/secret -- print
        # a concise, single-line ERROR (never a raw traceback) and fail
        # closed. This never falls through to a success-shaped return.
        print(f"ERROR: bundle publication failed ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1

    manifest = result["manifest"]
    print(f"bundle written: {result['write_result']['run_dir']}")
    print(
        f"sources={manifest['counts']['sources']} artifacts={manifest['counts']['artifacts']} "
        f"content_hash={manifest['content_hash']}"
    )

    if args.summary_output is not None:
        summary = build_pilot_summary(manifest)
        args.summary_output.parent.mkdir(parents=True, exist_ok=True)
        args.summary_output.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8",
        )
        print(f"summary written: {args.summary_output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
