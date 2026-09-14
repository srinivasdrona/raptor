#!/usr/bin/env python
"""Fetch and verify the RAPTOR v2 R611Q literature-expansion bundle
(``docs/project/specs/raptor-v2-r611q-literature-expansion-v1.yaml``).

This is the ONLY module in this slice that performs real network I/O --
``raptor.external.r611q_literature`` is pure, deterministic parsing/
validation/hashing/manifest construction over injected bytes (see that
package's module docstrings). This script:

1. Loads ``configs/external/r611q_literature_expansion_v1.yaml`` (the
   variant identity, baseline pin, and the six literature sources).
2. Reads and parses the pinned baseline discovery-shelf manifest (an
   external, already-fetched file -- never re-derived over the network).
3. Fetches LitVar2's "get publications" JSON, ClinVar's ESearch (rsID ->
   UID) and ELink (``clinvar_pubmed``) JSON responses, and derives the
   PMID discovery-lead union minus the baseline.
4. Fetches PubMed EFetch XML metadata/abstracts and Europe PMC "core"
   JSON identity/licence enrichment for every new PMID lead, then
   downloads JATS full text ONLY for PMCIDs whose Europe PMC metadata
   reports exactly CC BY (re-verifying the JATS document's own licence
   declaration independently before accepting it).
5. Builds the per-lead article index and publishes an external,
   create-only, hash-verified bundle (``raptor.external.r611q_literature.
   bundle``).

``--dry-run`` performs ONLY config/baseline-file/endpoint-plan validation:
it never builds a transport and never calls the real ingestion path, so it
makes no network call and writes nothing.

NCBI Entrez/LitVar2 and Europe PMC calls are conservatively, serially
rate-limited (``--min-ncbi-interval-seconds``, default 0.34s -- the
documented safe NCBI interval without an API key) via a single shared
rate limiter keyed by host; this script never issues concurrent requests.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from raptor.external.r611q_literature import bundle as bundle_mod  # noqa: E402
from raptor.external.r611q_literature import endpoint as endpoint_mod  # noqa: E402
from raptor.external.r611q_literature import parse as parse_mod  # noqa: E402

DEFAULT_EXTERNAL_ROOT_ENV = "RAPTOR_R611Q_LITERATURE_ROOT"
DEFAULT_EXTERNAL_ROOT = Path.home() / "raptor-data" / "external" / "r611q-literature"
DEFAULT_CONFIG = REPO_ROOT / "configs" / "external" / "r611q_literature_expansion_v1.yaml"
DEFAULT_MIN_NCBI_INTERVAL_SECONDS = 0.34
_RATE_LIMITED_HOSTS = frozenset(
    {"eutils.ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov", "www.ebi.ac.uk"}
)
_REQUEST_TIMEOUT_SECONDS = 30.0
_USER_AGENT = "raptor-r611q-literature-expansion/1.0 (+https://github.com/srinivasdrona/raptor)"


class R611QOperatorError(RuntimeError):
    """Base error for the R611Q literature-expansion operator CLI."""


def resolve_external_root(config: dict[str, Any]) -> Path:
    env_name = config.get("output", {}).get("environment_variable", DEFAULT_EXTERNAL_ROOT_ENV)
    return Path(os.environ.get(env_name) or DEFAULT_EXTERNAL_ROOT).expanduser()


class _RateLimiter:
    """Enforces a minimum interval between successive requests to the same
    host (keyed by ``netloc``); hosts with no configured interval are never
    throttled. Requests are always issued serially -- this script never
    fans out concurrent transport calls."""

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


def _require(config: dict[str, Any], *path: str) -> Any:
    node: Any = config
    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise R611QOperatorError(f"config is missing required key: {'.'.join(path)!r}")
        node = node[key]
    return node


def _validate_plan(config: dict[str, Any]) -> dict[str, Any]:
    """Build (and, by construction, validate) every endpoint this run will
    ever request -- this is the "endpoint plan" a ``--dry-run`` validates
    without ever calling a transport."""
    variant = _require(config, "variant")
    litvar_id = variant["litvar_id"]
    rsid = variant["rsid"]
    clinvar_uid = variant["clinvar_uid"]
    tool = config.get("ncbi_tool", "raptor")

    litvar_url = endpoint_mod.build_litvar_publications_url(litvar_id=litvar_id)
    esearch_url = endpoint_mod.build_clinvar_esearch_url(rsid=rsid, retmax=20, tool=tool)
    elink_url = endpoint_mod.build_clinvar_elink_url(uid=clinvar_uid, tool=tool)

    for requested, final in ((litvar_url, litvar_url), (esearch_url, esearch_url), (elink_url, elink_url)):
        endpoint_mod.assert_allowed_final_url(requested_url=requested, final_url=final)

    return {
        "litvar_url": litvar_url,
        "esearch_url": esearch_url,
        "elink_url": elink_url,
        "tool": tool,
        "clinvar_uid": clinvar_uid,
    }


def _resolve_committed_summary_target(args: argparse.Namespace, config: dict[str, Any]) -> Path | None:
    """Resolve and pre-validate the optional ``--summary-output`` target
    BEFORE any network call or bundle publication: returns ``None`` when
    the flag was not supplied. Otherwise the supplied path, once
    resolved, must lie inside ``REPO_ROOT`` and must equal EXACTLY
    ``REPO_ROOT / config['committed_summary_path']`` -- any other path
    (inside or outside the repository) is rejected rather than accepted
    as an alternate destination. Since the summary file is create-only,
    an already-existing target is ALSO rejected here -- before any
    network access or bundle publication -- rather than only failing
    later at write time. This validation runs identically for a
    ``--dry-run`` invocation and a real run: a ``--dry-run`` never writes
    the file, but still rejects an invalid/pre-existing target the same
    way a real run would."""
    raw = args.summary_output
    if raw is None:
        return None
    resolved = Path(raw).resolve()
    try:
        resolved.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise R611QOperatorError(
            f"summary-output path {resolved} is not inside the repository root {REPO_ROOT}; "
            "only the exact configured committed_summary_path target is ever accepted"
        ) from exc
    expected = (REPO_ROOT / config["committed_summary_path"]).resolve()
    if resolved != expected:
        raise R611QOperatorError(
            f"summary-output path {resolved} does not equal the exact configured "
            f"committed_summary_path target {expected}; an alternate path is never accepted"
        )
    if resolved.exists():
        raise R611QOperatorError(
            f"summary-output target already exists; the committed summary is create-only and "
            f"is never overwritten: {resolved}"
        )
    return resolved


def _load_baseline_bytes(baseline_manifest_path: Path) -> bytes:
    if not baseline_manifest_path.is_file():
        raise R611QOperatorError(f"baseline manifest not found: {baseline_manifest_path}")
    return baseline_manifest_path.read_bytes()


def _validate_rate_limit_override(value: Any, config: dict[str, Any]) -> float:
    """Validate a caller-supplied ``--min-ncbi-interval-seconds`` override
    BEFORE any transport is ever constructed: it must be a genuine,
    non-bool, finite number (never NaN/inf, never a string) that is
    strictly positive, and it must be at least the configured rate-limit
    floor -- the maximum of ``rate_limits.ncbi_without_api_key_min_
    interval_seconds`` and ``rate_limits.europe_pmc_min_interval_seconds``
    (falling back to ``DEFAULT_MIN_NCBI_INTERVAL_SECONDS`` for either when
    the config carries no ``rate_limits`` section at all). A caller may
    only ever REQUEST a slower (higher) request spacing than the
    configured floor, never a faster one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise R611QOperatorError(
            f"--min-ncbi-interval-seconds must be a genuine number (never a bool): {value!r}"
        )
    numeric = float(value)
    if not math.isfinite(numeric):
        raise R611QOperatorError(
            f"--min-ncbi-interval-seconds must be finite (NaN/inf are rejected): {value!r}"
        )
    if numeric <= 0:
        raise R611QOperatorError(
            f"--min-ncbi-interval-seconds must be strictly positive: {value!r}"
        )

    rate_limits_cfg = config.get("rate_limits")
    if not isinstance(rate_limits_cfg, dict):
        rate_limits_cfg = {}
    floor = max(
        float(
            rate_limits_cfg.get(
                "ncbi_without_api_key_min_interval_seconds", DEFAULT_MIN_NCBI_INTERVAL_SECONDS
            )
        ),
        float(
            rate_limits_cfg.get(
                "europe_pmc_min_interval_seconds", DEFAULT_MIN_NCBI_INTERVAL_SECONDS
            )
        ),
    )
    if numeric < floor:
        raise R611QOperatorError(
            f"--min-ncbi-interval-seconds {numeric!r} is below the configured minimum "
            f"rate-limit floor {floor!r}; only a value at or above the configured floor is "
            f"ever accepted (a caller may only request slower spacing, never faster)"
        )
    return numeric


def _validate_probe_reference_counts(*, observed: dict[str, Any], expected: dict[str, Any]) -> None:
    """Structurally validate every probe axis derived from this run's
    actually-parsed data (``observed``) against the config's
    ``probe_reference_counts`` (``expected``) BEFORE any publication step.
    Both mappings must carry EXACTLY the same key set (a missing or an
    extra key is rejected), and every value on both sides must be a
    genuine, non-bool, non-float integer -- a ``True``/``False`` or a
    ``float`` value is rejected even when numerically equal, never
    silently coerced/compared loosely. Differing integer VALUES between
    ``observed`` and ``expected`` are always accepted: the reference is a
    diagnostic planning aid, never an acceptance gate, so live source
    count drift never fails this check or blocks publication (spec
    ``delivery_checks``: "live source counts are recorded; the planning
    reference is diagnostic only")."""
    observed_keys = set(observed)
    expected_keys = set(expected)
    if observed_keys != expected_keys:
        missing = sorted(expected_keys - observed_keys)
        extra = sorted(observed_keys - expected_keys)
        raise R611QOperatorError(
            f"probe reference-count key set mismatch: missing={missing!r} extra={extra!r}"
        )
    for key in sorted(expected_keys):
        observed_value = observed[key]
        expected_value = expected[key]
        if not isinstance(observed_value, int) or isinstance(observed_value, bool):
            raise R611QOperatorError(
                f"observed probe count {key!r} must be a plain int (never bool/float): "
                f"{observed_value!r}"
            )
        if not isinstance(expected_value, int) or isinstance(expected_value, bool):
            raise R611QOperatorError(
                f"reference probe count {key!r} must be a plain int (never bool/float): "
                f"{expected_value!r}"
            )


def run_ingestion(
    *,
    config: dict[str, Any],
    baseline_manifest_path: Path,
    transport: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    """Run the full acquisition: baseline pin -> LitVar2/ClinVar discovery
    -> PubMed EFetch -> Europe PMC core -> exactly-eligible CC BY full
    text -> article index -> bundle manifest. Structurally validates
    every derived probe axis against the config's diagnostic
    ``probe_reference_counts`` before returning -- key-set/type mismatches
    are rejected, but drifting count VALUES are diagnostic-only and never
    fail this run or block publication. Returns ``{"manifest",
    "artifact_payloads"}`` -- it never publishes the bundle itself (that
    is ``main``'s job, so the publication step is explicit and always
    precedes any committed-summary build/write) and never writes the
    committed summary."""
    plan = _validate_plan(config)
    baseline_cfg = _require(config, "baseline")
    baseline_expected = baseline_cfg.get("expected") or {}
    baseline_bytes = _load_baseline_bytes(baseline_manifest_path)
    baseline = parse_mod.parse_baseline_manifest(
        payload_bytes=baseline_bytes,
        expected_schema=baseline_cfg["schema"],
        expected_sha256=baseline_cfg["sha256"],
        expected_byte_length=baseline_cfg["byte_length"],
        expected_pmid_publications=baseline_expected.get("pmid_publications"),
        expected_doi_only_publications=baseline_expected.get("doi_only_publications"),
    )

    artifacts: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _fetch(source_id: str, url: str, *, role: str, relative_path: str) -> dict[str, Any]:
        fetched = endpoint_mod.request_with_transport(requested_url=url, transport=transport)
        artifacts.append(
            {
                "artifact_id": f"raw-{source_id}",
                "source_id": source_id,
                "role": role,
                "requested_url": fetched["requested_url"],
                "final_url": fetched["final_url"],
                "http_status": fetched["http_status"],
                "media_type": fetched["media_type"],
                "relative_path": relative_path,
                "byte_length": fetched["byte_length"],
                "sha256": fetched["sha256"],
                "md5": __import__("hashlib").md5(fetched["body"]).hexdigest(),  # nosec B303
                "fetched_at": created_at,
                "verification": "HASHED",
            }
        )
        sources.append(
            {
                "source_id": source_id,
                "source_kind": source_id,
                "lifecycle_state": "STAGED_VERIFIED",
                "access_state": "PUBLIC",
                "licence_state": "PUBLIC_METADATA",
                "permitted_use": "NON_CLINICAL_DISCOVERY",
                "identifiers": {"primary": source_id},
                "artifact_ids": [f"raw-{source_id}"],
                "observations": {},
                "limitations": [],
            }
        )
        return fetched

    litvar_fetch = _fetch(
        "litvar2_publications", plan["litvar_url"],
        role="RAW_RESPONSE", relative_path="raw/litvar2-publications.json",
    )
    litvar = parse_mod.parse_litvar_publications(litvar_fetch["body"].decode("utf-8"))

    esearch_fetch = _fetch(
        "clinvar_uid_search", plan["esearch_url"],
        role="RAW_RESPONSE", relative_path="raw/clinvar-esearch.json",
    )
    parse_mod.parse_clinvar_uid_esearch(
        esearch_fetch["body"].decode("utf-8"), expected_uid=plan["clinvar_uid"]
    )

    elink_fetch = _fetch(
        "clinvar_pubmed_links", plan["elink_url"],
        role="RAW_RESPONSE", relative_path="raw/clinvar-pubmed-links.json",
    )
    clinvar_pmids = parse_mod.parse_clinvar_pubmed_links(
        elink_fetch["body"].decode("utf-8"), expected_uid=plan["clinvar_uid"]
    )

    membership = parse_mod.derive_discovery_membership(
        litvar_pmids=litvar["pmids"],
        clinvar_pmids=clinvar_pmids,
        baseline_pmids=baseline["pmid_publications"],
    )
    new_pmids = membership["new_pmids"]

    pubmed_articles: list[dict[str, Any]] = []
    pubmed_missing: list[str] = []
    pubmed_fetch: dict[str, Any] | None = None
    if new_pmids:
        pubmed_cfg = _require(config, "sources", "pubmed")
        batch_size = pubmed_cfg.get("batch_size")
        if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size <= 0:
            raise R611QOperatorError(
                f"pubmed batch_size must be a positive integer: {batch_size!r}"
            )
        if len(new_pmids) > batch_size:
            raise R611QOperatorError(
                f"the derived new-PMID set ({len(new_pmids)}) exceeds the configured pubmed "
                f"batch_size ({batch_size}); this slice requires every new-PMID lead to fit "
                f"in a single bounded EFetch batch and fails rather than silently broadening "
                f"to multiple batches"
            )

        efetch_url = endpoint_mod.build_pubmed_efetch_url(pmids=new_pmids, tool=plan["tool"])
        pubmed_fetch = endpoint_mod.request_with_transport(requested_url=efetch_url, transport=transport)
        parsed = parse_mod.parse_pubmed_articles_xml(
            pubmed_fetch["body"].decode("utf-8"), expected_pmids=new_pmids
        )
        pubmed_articles = parsed["articles"]
        pubmed_missing = parsed["requested_but_missing_pmids"]

        artifacts.append(
            {
                "artifact_id": "raw-pubmed",
                "source_id": "pubmed",
                "role": "RAW_RESPONSE",
                "requested_url": pubmed_fetch["requested_url"],
                "final_url": pubmed_fetch["final_url"],
                "http_status": pubmed_fetch["http_status"],
                "media_type": pubmed_fetch["media_type"],
                "relative_path": "raw/pubmed-efetch.xml",
                "byte_length": pubmed_fetch["byte_length"],
                "sha256": pubmed_fetch["sha256"],
                "md5": __import__("hashlib").md5(pubmed_fetch["body"]).hexdigest(),  # nosec B303
                "fetched_at": created_at,
                "verification": "HASHED",
            }
        )
        sources.append(
            {
                "source_id": "pubmed",
                "source_kind": "pubmed",
                "lifecycle_state": "STAGED_VERIFIED",
                "access_state": "PUBLIC",
                "licence_state": "PUBLIC_METADATA",
                "permitted_use": "NON_CLINICAL_DISCOVERY",
                "identifiers": {"primary": "pubmed"},
                "artifact_ids": ["raw-pubmed"],
                "observations": {"requested_but_missing_pmids": pubmed_missing},
                "limitations": [],
            }
        )

    europe_pmc_records: list[dict[str, Any]] = []
    europe_pmc_unresolved: list[str] = []
    if new_pmids:
        europe_pmc_cfg = _require(config, "sources", "europe_pmc")
        page_size = int(europe_pmc_cfg.get("page_size", 1000))
        core_url = endpoint_mod.build_europe_pmc_core_url(pmids=new_pmids, page_size=page_size)
        core_fetch = _fetch(
            "europe_pmc", core_url, role="RAW_RESPONSE", relative_path="raw/europepmc-core.json",
        )
        parsed = parse_mod.parse_europe_pmc_core(
            core_fetch["body"].decode("utf-8"), requested_pmids=new_pmids
        )
        europe_pmc_records = parsed["records"]
        europe_pmc_unresolved = parsed["requested_but_unresolved_pmids"]

    fulltext_status_by_pmcid: dict[str, dict[str, Any]] = {}
    fulltext_bytes_by_pmcid: dict[str, bytes] = {}
    fulltext_pmcids = parse_mod.select_cc_by_fulltext_candidates(europe_pmc_records)
    for pmcid in fulltext_pmcids:
        fulltext_url = endpoint_mod.build_europe_pmc_fulltext_xml_url(pmcid=pmcid)
        fetched = endpoint_mod.request_with_transport(requested_url=fulltext_url, transport=transport)
        try:
            parse_mod.parse_cc_by_jats_fulltext(
                fetched["body"].decode("utf-8"), expected_pmcid=pmcid
            )
        except parse_mod.JatsLicenceRejectedError:
            # The Europe PMC "core" metadata reported exactly CC BY, but the
            # JATS document itself does not carry an explicit CC BY
            # declaration -- this is a typed, per-record disposition (never
            # a silently-swallowed broad catch): only this specific licence-
            # rejection subclass is caught here, so the candidate is
            # recorded as JATS_LICENCE_REJECTED with no artifact/bytes
            # retained, and every OTHER candidate is still evaluated
            # independently. A `JatsIdentityError` (malformed XML/article-
            # meta, missing/mismatched pmcid) is a DIFFERENT, narrower
            # subclass that is deliberately NOT caught here -- it remains
            # fatal to the whole run, exactly like a transport failure.
            fulltext_status_by_pmcid[pmcid] = {
                "fulltext_status": "JATS_LICENCE_REJECTED",
                "artifact_id": None,
            }
            continue
        artifact_id = f"fulltext-{pmcid}"
        artifacts.append(
            {
                "artifact_id": artifact_id,
                "source_id": "fulltext",
                "role": "FULLTEXT_XML",
                "requested_url": fetched["requested_url"],
                "final_url": fetched["final_url"],
                "http_status": fetched["http_status"],
                "media_type": fetched["media_type"],
                "relative_path": f"fulltext/{pmcid}.xml",
                "byte_length": fetched["byte_length"],
                "sha256": fetched["sha256"],
                "md5": __import__("hashlib").md5(fetched["body"]).hexdigest(),  # nosec B303
                "fetched_at": created_at,
                "verification": "HASHED",
            }
        )
        fulltext_bytes_by_pmcid[pmcid] = fetched["body"]
        fulltext_status_by_pmcid[pmcid] = {
            "fulltext_status": "ACQUIRED_CC_BY",
            "artifact_id": artifact_id,
        }
    fulltext_acquired_pmcids = [
        pmcid
        for pmcid, entry in fulltext_status_by_pmcid.items()
        if entry["fulltext_status"] == "ACQUIRED_CC_BY"
    ]
    if fulltext_acquired_pmcids:
        sources.append(
            {
                "source_id": "fulltext",
                "source_kind": "fulltext",
                "lifecycle_state": "STAGED_VERIFIED",
                "access_state": "PUBLIC",
                "licence_state": "CC_BY",
                "permitted_use": "NON_CLINICAL_DISCOVERY",
                "identifiers": {"primary": "fulltext"},
                "artifact_ids": [f"fulltext-{pmcid}" for pmcid in fulltext_acquired_pmcids],
                "observations": {"candidates": len(fulltext_pmcids)},
                "limitations": [],
            }
        )

    article_rows = parse_mod.build_article_index_records(
        new_pmids=new_pmids,
        source_membership=membership["source_membership"],
        pubmed_articles=pubmed_articles,
        europe_pmc_records=europe_pmc_records,
        fulltext_status_by_pmcid=fulltext_status_by_pmcid,
    )
    article_index_body = parse_mod.to_article_index_jsonl(article_rows).encode("utf-8")
    article_index_artifact_id = "normalized-article-index"
    artifacts.append(
        {
            "artifact_id": article_index_artifact_id,
            "source_id": "article_index",
            "role": "ARTICLE_INDEX",
            "requested_url": "derived",
            "final_url": "derived",
            "http_status": 200,
            "media_type": "application/jsonl",
            "relative_path": "normalized/article-index.jsonl",
            "byte_length": len(article_index_body),
            "sha256": __import__("hashlib").sha256(article_index_body).hexdigest(),
            "md5": __import__("hashlib").md5(article_index_body).hexdigest(),  # nosec B303
            "fetched_at": created_at,
            "verification": "HASHED",
        }
    )
    sources.append(
        {
            "source_id": "article_index",
            "source_kind": "article_index",
            "lifecycle_state": "STAGED_VERIFIED",
            "access_state": "PUBLIC",
            "licence_state": "PUBLIC_METADATA",
            "permitted_use": "NON_CLINICAL_DISCOVERY",
            "identifiers": {"primary": "article_index"},
            "artifact_ids": [article_index_artifact_id],
            "observations": {"row_count": len(article_rows)},
            "limitations": [],
        }
    )

    licence_counts: dict[str, int] = {"CC BY": 0, "CC BY-NC-ND": 0, "CC BY-NC-SA": 0, "ABSENT": 0}
    for row in europe_pmc_records:
        licence = row.get("licence")
        key = licence if licence is not None else "ABSENT"
        licence_counts[key] = licence_counts.get(key, 0) + 1

    observed_counts = {
        "litvar2_pmids": membership["litvar2_pmids"],
        "clinvar_pmids": membership["clinvar_pmids"],
        "litvar2_clinvar_intersection": membership["intersection_pmids"],
        "discovery_union_pmids": membership["union_pmids"],
        "baseline_union_overlap": membership["union_pmids"] - len(new_pmids),
        "new_pmid_leads": len(new_pmids),
        "pubmed_records_returned": len(pubmed_articles),
        "pubmed_records_unresolved": len(pubmed_missing),
        "pubmed_abstracts": sum(1 for row in pubmed_articles if row.get("abstract") is not None),
        "pubmed_pmcids": sum(1 for row in pubmed_articles if row.get("pmcid") is not None),
        "pubmed_dois": sum(1 for row in pubmed_articles if row.get("doi") is not None),
        "europe_pmc_records_returned": len(europe_pmc_records),
        "europe_pmc_abstracts": sum(1 for row in europe_pmc_records if row.get("abstract") is not None),
        "europe_pmc_pmcids": sum(1 for row in europe_pmc_records if row.get("pmcid") is not None),
        "europe_pmc_open_access": sum(1 for row in europe_pmc_records if row.get("is_open_access") == "Y"),
        "licence_cc_by": licence_counts["CC BY"],
        "licence_cc_by_nc_nd": licence_counts["CC BY-NC-ND"],
        "licence_cc_by_nc_sa": licence_counts["CC BY-NC-SA"],
        "licence_absent": licence_counts["ABSENT"],
        "fulltext_candidates": len(fulltext_pmcids),
    }
    probe_reference_counts = _require(config, "probe_reference_counts")
    _validate_probe_reference_counts(observed=observed_counts, expected=probe_reference_counts)

    manifest = bundle_mod.build_bundle_manifest(
        bundle_id=config["bundle_id"],
        created_at=created_at,
        query={"gene": config["variant"]["gene"], "rsid": config["variant"]["rsid"]},
        artifacts=artifacts,
        sources=sources,
        truncation={},
        boundaries={"network": "operator-only", "external_output_only": True},
        baseline_hashes={"baseline_manifest": baseline["raw_sha256"]},
        licence_counts=licence_counts,
        unresolved={
            "pubmed_missing_pmids": pubmed_missing,
            "europe_pmc_unresolved_pmids": europe_pmc_unresolved,
        },
        counts={
            **observed_counts,
            "article_index_rows": len(article_rows),
        },
    )

    artifact_payloads: dict[str, bytes] = {"normalized/article-index.jsonl": article_index_body}
    artifact_payloads["raw/litvar2-publications.json"] = litvar_fetch["body"]
    artifact_payloads["raw/clinvar-esearch.json"] = esearch_fetch["body"]
    artifact_payloads["raw/clinvar-pubmed-links.json"] = elink_fetch["body"]
    if new_pmids:
        artifact_payloads["raw/pubmed-efetch.xml"] = pubmed_fetch["body"]
        artifact_payloads["raw/europepmc-core.json"] = core_fetch["body"]
    for pmcid in fulltext_acquired_pmcids:
        artifact_payloads[f"fulltext/{pmcid}.xml"] = fulltext_bytes_by_pmcid[pmcid]

    return {"manifest": manifest, "artifact_payloads": artifact_payloads}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG,
        help=f"R611Q literature-expansion YAML config (default: {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--output-root", type=Path, default=None,
        help=(
            "external run root (default: $RAPTOR_R611Q_LITERATURE_ROOT or "
            "~/raptor-data/external/r611q-literature)"
        ),
    )
    parser.add_argument(
        "--run-name", default=None,
        help="external run directory name (default: config run_name)",
    )
    parser.add_argument(
        "--baseline-manifest", type=Path, required=True,
        help="path to the pinned baseline discovery-shelf manifest JSON file",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help=(
            "validate config/baseline-file presence and the endpoint plan only; "
            "makes no transport call and writes nothing"
        ),
    )
    parser.add_argument(
        "--min-ncbi-interval-seconds", type=float, default=DEFAULT_MIN_NCBI_INTERVAL_SECONDS,
        help=f"minimum seconds between requests to a rate-limited host (default: {DEFAULT_MIN_NCBI_INTERVAL_SECONDS})",
    )
    parser.add_argument(
        "--ncbi-tool", default="raptor",
        help="Entrez 'tool' query parameter value (default: raptor)",
    )
    parser.add_argument(
        "--summary-output", type=Path, default=None,
        help=(
            "optional path to write the aggregate-only committed summary JSON "
            "(must resolve to exactly the configured committed_summary_path); "
            "create-only, never written unless explicitly supplied and never "
            "written by --dry-run"
        ),
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
    config["ncbi_tool"] = args.ncbi_tool

    try:
        output_root = args.output_root or resolve_external_root(config)
        run_name = args.run_name or config["run_name"]
        _validate_plan(config)
        if not args.baseline_manifest.is_file():
            raise R611QOperatorError(f"baseline manifest not found: {args.baseline_manifest}")
        summary_target = _resolve_committed_summary_target(args, config)
    except (KeyError, R611QOperatorError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(
            "dry-run: config, baseline-manifest path, endpoint plan and summary-output "
            "target validated; no network calls or writes performed"
        )
        print(f"  output_root={output_root} run_name={run_name}")
        return 0

    try:
        validated_min_interval = _validate_rate_limit_override(args.min_ncbi_interval_seconds, config)
    except R611QOperatorError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    rate_limiter = _RateLimiter(
        {host: validated_min_interval for host in _RATE_LIMITED_HOSTS}
    )
    transport = _make_transport(rate_limiter)

    try:
        result = run_ingestion(
            config=config,
            baseline_manifest_path=args.baseline_manifest,
            transport=transport,
        )
    except (
        parse_mod.R611QLiteratureParseError,
        endpoint_mod.EndpointSecurityError,
        endpoint_mod.TransportValidationError,
        R611QOperatorError,
    ) as exc:
        print(f"ERROR: ingestion failed ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1

    manifest = result["manifest"]

    try:
        write_result = bundle_mod.write_bundle_run(
            repo_root=REPO_ROOT,
            output_root=output_root,
            run_name=run_name,
            manifest=manifest,
            artifact_payloads=result["artifact_payloads"],
        )
    except (bundle_mod.BundleBoundaryError, bundle_mod.BundleHashMismatchError) as exc:
        print(f"ERROR: bundle publication failed ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1

    print(f"bundle written: {write_result['run_dir']}")
    print(
        f"sources={manifest['counts']['sources']} artifacts={manifest['counts']['artifacts']} "
        f"content_hash={manifest['content_hash']}"
    )

    if summary_target is not None:
        try:
            summary = bundle_mod.build_committed_summary(manifest)
            payload = (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode("utf-8")
            summary_target.parent.mkdir(parents=True, exist_ok=True)
            with open(str(summary_target), "xb") as handle:
                handle.write(payload)
        except (bundle_mod.BundleBoundaryError, bundle_mod.BundleHashMismatchError, OSError) as exc:
            # Sanitized, single-line, typed failure -- never a raw traceback:
            # the bundle itself was already published successfully above, and
            # only the (separately opted-into) committed-summary write failed.
            print(
                f"ERROR: failed to write committed summary (create-only) to "
                f"{summary_target} ({type(exc).__name__}): {exc}",
                file=sys.stderr,
            )
            return 1
        print(f"summary written: {args.summary_output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

