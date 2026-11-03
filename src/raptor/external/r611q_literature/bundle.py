"""External R611Q literature-expansion bundle manifest, canonical hashing,
create-only/symlink-safe atomic publication, and a compact, aggregate-only
committed summary.

This module performs no network I/O. It reuses
`raptor.external.tsc2_sources.bundle`'s already-hardened artifact/source
schema validation, forbidden-status-vocabulary check, canonical content
hashing and external/create-only/symlink-safe atomic run publication,
rather than re-implementing them -- this package's artifact/source record
shapes are identical to that sibling package's.

`build_bundle_manifest` additionally carries this package's own
provenance fields on top of the shared artifact/source schema:
`baseline_hashes` (the pinned baseline manifest's own SHA-256, keyed by
whatever the caller names it), `source_response_hashes` (one SHA-256 per
raw source response artifact), `licence_counts`, `unresolved` (never
empty -- see below) and a derived, sorted `fulltext_artifact_hashes` list.
Every one of these is folded into the manifest BEFORE its canonical
`content_hash` is computed, so the self-hash covers them too.

`validate_manifest_hash` is this package's OWN strict extension-schema
validator (never merely the generic, hash-only check `tsc2_sources.bundle`
performs): exact top-level field set/schema, the shared artifact/source
checks, 64-hex-character hash values, non-negative integer counts with
their cross-checks (`sources`/`artifacts` against the actual list
lengths; `fulltext_acquired` against `len(fulltext_artifact_hashes)`;
`fulltext_candidates >= fulltext_acquired`; `new_pmids ==
article_index_rows` when both are present), a self-sorted/deduplicated/
valid-hex `fulltext_artifact_hashes` list, and `unresolved` PMID lists
that are each unique and numeric -- THEN the manifest's own canonical
content hash. `build_committed_summary` always validates a manifest this
way FIRST, before ever projecting it.

`build_committed_summary` is a strict field-whitelist projection: it NEVER
includes a requested/final URL, a PMID, PMCID, DOI, title, abstract or
full text -- only aggregate hashes/counts, coerced `unresolved_counts`
(list lengths, never the PMIDs themselves) and the manifest's own
boundaries statement.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from raptor.external.tsc2_sources.bundle import (
    BundleBoundaryError,
    BundleHashMismatchError,
    StatusVocabularyError,
    assert_no_forbidden_status_vocabulary,
    compute_bundle_content_hash,
)
from raptor.external.tsc2_sources.bundle import (
    _validate_artifact_schema,
    _validate_cross_references,
    _validate_source_schema,
)
from raptor.external.tsc2_sources.bundle import validate_manifest_hash as _shared_validate_manifest_hash
from raptor.external.tsc2_sources.bundle import write_bundle_run as _shared_write_bundle_run

BUNDLE_MANIFEST_SCHEMA = "raptor.external.r611q_literature_bundle.v1"
COMMITTED_SUMMARY_SCHEMA = "raptor.external.r611q_literature_committed_summary.v1"
MANIFEST_FILENAME = "bundle_manifest.json"

_RAW_RESPONSE_ROLE = "RAW_RESPONSE"
_FULLTEXT_ROLE = "FULLTEXT_XML"

_HEX64_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_PMID_PATTERN = re.compile(r"^\d+$")

#: The manifest's exact top-level field set (beyond this, and never
#: less): an arbitrary/unexpected key anywhere at this level is rejected
#: rather than silently ignored.
_MANIFEST_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema",
        "bundle_id",
        "created_at",
        "query",
        "artifacts",
        "sources",
        "counts",
        "truncation",
        "boundaries",
        "baseline_hashes",
        "source_response_hashes",
        "licence_counts",
        "unresolved",
        "fulltext_artifact_hashes",
        "content_hash",
    }
)
#: Count keys `build_bundle_manifest` always populates and `validate_
#: manifest_hash` always cross-checks; a manifest is free to carry
#: additional count keys (e.g. `new_pmids`/`article_index_rows`), which
#: are only cross-checked against each other when BOTH are present.
_REQUIRED_COUNT_KEYS = frozenset({"sources", "artifacts", "fulltext_candidates", "fulltext_acquired"})


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_of(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _assert_hex64(value: Any, *, label: str) -> None:
    if not isinstance(value, str) or not _HEX64_PATTERN.match(value):
        raise BundleHashMismatchError(f"{label} is not a 64-character hex sha256 string: {value!r}")


def _assert_nonneg_int(value: Any, *, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise BundleBoundaryError(f"{label} must be a non-negative integer (never a bool): {value!r}")


def _assert_unique_pmid_list(value: Any, *, label: str) -> None:
    if not isinstance(value, list):
        raise BundleBoundaryError(f"{label} must be a list of pmid strings: {value!r}")
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not _PMID_PATTERN.match(item):
            raise BundleBoundaryError(f"{label} has a malformed pmid: {item!r}")
        if item in seen:
            raise BundleBoundaryError(f"{label} has a duplicate pmid: {item!r}")
        seen.add(item)


def _validate_extended_manifest_schema(manifest: dict[str, Any]) -> None:
    """Validate everything this package's manifest extension adds on top
    of the shared artifact/source schema (see the module docstring).
    Raises ``BundleBoundaryError``/``BundleHashMismatchError`` on any
    violation; never silently coerces a malformed/mutated field."""
    if not isinstance(manifest, dict):
        raise BundleBoundaryError(f"manifest must be a mapping: {type(manifest).__name__}")

    keys = set(manifest)
    if keys != _MANIFEST_TOP_LEVEL_FIELDS:
        missing = _MANIFEST_TOP_LEVEL_FIELDS - keys
        extra = keys - _MANIFEST_TOP_LEVEL_FIELDS
        raise BundleBoundaryError(
            "manifest does not have the exact required top-level fields/keys: "
            f"missing={sorted(missing)!r} extra={sorted(extra)!r}"
        )
    if manifest["schema"] != BUNDLE_MANIFEST_SCHEMA:
        raise BundleBoundaryError(
            f"manifest schema {manifest['schema']!r} does not match expected "
            f"{BUNDLE_MANIFEST_SCHEMA!r}"
        )

    artifacts = manifest["artifacts"]
    sources = manifest["sources"]
    if not isinstance(artifacts, list) or not isinstance(sources, list):
        raise BundleBoundaryError("manifest 'artifacts'/'sources' must each be a list")
    for artifact in artifacts:
        _validate_artifact_schema(artifact)
    for source in sources:
        _validate_source_schema(source)
    assert_no_forbidden_status_vocabulary(sources)
    _validate_cross_references(artifacts, sources)

    baseline_hashes = manifest["baseline_hashes"]
    if not isinstance(baseline_hashes, dict) or not baseline_hashes:
        raise BundleBoundaryError("manifest 'baseline_hashes' must be a non-empty mapping")
    for key, value in baseline_hashes.items():
        _assert_hex64(value, label=f"baseline_hashes[{key!r}]")

    source_response_hashes = manifest["source_response_hashes"]
    if not isinstance(source_response_hashes, dict) or not source_response_hashes:
        raise BundleBoundaryError("manifest 'source_response_hashes' must be a non-empty mapping")
    for key, value in source_response_hashes.items():
        _assert_hex64(value, label=f"source_response_hashes[{key!r}]")
    derived_source_response_hashes = {
        artifact["source_id"]: artifact["sha256"]
        for artifact in artifacts
        if artifact.get("role") == _RAW_RESPONSE_ROLE
    }
    if derived_source_response_hashes and source_response_hashes != derived_source_response_hashes:
        raise BundleBoundaryError(
            "manifest 'source_response_hashes' does not exactly equal the derived mapping "
            f"from RAW_RESPONSE artifacts: recorded={source_response_hashes!r} "
            f"derived={derived_source_response_hashes!r}"
        )

    licence_counts = manifest["licence_counts"]
    if not isinstance(licence_counts, dict):
        raise BundleBoundaryError("manifest 'licence_counts' must be a mapping")
    for key, value in licence_counts.items():
        _assert_nonneg_int(value, label=f"licence_counts[{key!r}]")

    unresolved = manifest["unresolved"]
    if not isinstance(unresolved, dict) or not unresolved:
        raise BundleBoundaryError("manifest 'unresolved' must be a non-empty mapping")
    for key, value in unresolved.items():
        _assert_unique_pmid_list(value, label=f"unresolved[{key!r}]")

    fulltext_artifact_hashes = manifest["fulltext_artifact_hashes"]
    if not isinstance(fulltext_artifact_hashes, list):
        raise BundleBoundaryError("manifest 'fulltext_artifact_hashes' must be a list")
    for value in fulltext_artifact_hashes:
        _assert_hex64(value, label="fulltext_artifact_hashes entry")
    if len(fulltext_artifact_hashes) != len(set(fulltext_artifact_hashes)):
        raise BundleBoundaryError(
            f"manifest 'fulltext_artifact_hashes' contains duplicate hash(es): "
            f"{fulltext_artifact_hashes!r}"
        )
    if fulltext_artifact_hashes != sorted(fulltext_artifact_hashes):
        raise BundleBoundaryError(
            "manifest 'fulltext_artifact_hashes' is invalid: entries must be unique, valid "
            f"sha256 hex and sorted ascending; got {fulltext_artifact_hashes!r}"
        )
    derived_fulltext_artifact_hashes = sorted(
        artifact["sha256"] for artifact in artifacts if artifact.get("role") == _FULLTEXT_ROLE
    )
    # Cross-checked against the real FULLTEXT_XML artifacts ONLY when this
    # manifest actually has real RAW_RESPONSE artifacts to derive `source_
    # response_hashes` from (i.e. it looks like a genuinely-built
    # acquisition manifest, not a synthetic/placeholder one whose
    # extension fields were hand-populated independently of `artifacts`).
    if derived_source_response_hashes and fulltext_artifact_hashes != derived_fulltext_artifact_hashes:
        raise BundleBoundaryError(
            "manifest 'fulltext_artifact_hashes' does not exactly equal the derived sorted "
            f"sha256 list of FULLTEXT_XML artifacts: recorded={fulltext_artifact_hashes!r} "
            f"derived={derived_fulltext_artifact_hashes!r}"
        )

    counts = manifest["counts"]
    if not isinstance(counts, dict):
        raise BundleBoundaryError("manifest 'counts' must be a mapping")
    missing_counts = _REQUIRED_COUNT_KEYS - set(counts)
    if missing_counts:
        raise BundleBoundaryError(f"manifest 'counts' is missing required key(s): {sorted(missing_counts)!r}")
    for key, value in counts.items():
        _assert_nonneg_int(value, label=f"counts[{key!r}]")
    if counts["sources"] != len(sources):
        raise BundleBoundaryError(
            f"manifest counts.sources {counts['sources']!r} does not equal len(sources) "
            f"{len(sources)!r}"
        )
    if counts["artifacts"] != len(artifacts):
        raise BundleBoundaryError(
            f"manifest counts.artifacts {counts['artifacts']!r} does not equal len(artifacts) "
            f"{len(artifacts)!r}"
        )
    if counts["fulltext_acquired"] != len(fulltext_artifact_hashes):
        raise BundleBoundaryError(
            f"manifest counts.fulltext_acquired {counts['fulltext_acquired']!r} does not equal "
            f"len(fulltext_artifact_hashes) {len(fulltext_artifact_hashes)!r}"
        )
    if counts["fulltext_candidates"] < counts["fulltext_acquired"]:
        raise BundleBoundaryError(
            f"manifest counts.fulltext_candidates {counts['fulltext_candidates']!r} must be "
            f">= counts.fulltext_acquired {counts['fulltext_acquired']!r}"
        )
    if "new_pmids" in counts and "article_index_rows" in counts:
        if counts["new_pmids"] != counts["article_index_rows"]:
            raise BundleBoundaryError(
                f"manifest counts.new_pmids {counts['new_pmids']!r} does not equal "
                f"counts.article_index_rows {counts['article_index_rows']!r}"
            )

    # Cross-axis arithmetic: enforced ONLY when the relevant probe axes are
    # actually present in `counts` (a minimal manifest that never populated
    # these optional axes is never forced to backfill them just to pass
    # validation) -- but whenever they ARE present, they must be mutually
    # consistent; a drifted probe axis is rejected exactly like a drifted
    # sources/artifacts/fulltext count.
    def _all_present(*keys: str) -> bool:
        return all(key in counts for key in keys)

    if _all_present("litvar2_pmids", "clinvar_pmids", "litvar2_clinvar_intersection", "discovery_union_pmids"):
        computed = counts["litvar2_pmids"] + counts["clinvar_pmids"] - counts["litvar2_clinvar_intersection"]
        if computed != counts["discovery_union_pmids"]:
            raise BundleBoundaryError(
                f"manifest counts arithmetic violation: litvar2_pmids + clinvar_pmids - "
                f"litvar2_clinvar_intersection ({computed!r}) does not equal "
                f"discovery_union_pmids ({counts['discovery_union_pmids']!r})"
            )
    if _all_present("baseline_union_overlap", "new_pmid_leads", "discovery_union_pmids"):
        computed = counts["baseline_union_overlap"] + counts["new_pmid_leads"]
        if computed != counts["discovery_union_pmids"]:
            raise BundleBoundaryError(
                f"manifest counts arithmetic violation: baseline_union_overlap + "
                f"new_pmid_leads ({computed!r}) does not equal discovery_union_pmids "
                f"({counts['discovery_union_pmids']!r})"
            )
    if _all_present("pubmed_records_returned", "pubmed_records_unresolved", "new_pmid_leads"):
        computed = counts["pubmed_records_returned"] + counts["pubmed_records_unresolved"]
        if computed != counts["new_pmid_leads"]:
            raise BundleBoundaryError(
                f"manifest counts arithmetic violation: pubmed_records_returned + "
                f"pubmed_records_unresolved ({computed!r}) does not equal new_pmid_leads "
                f"({counts['new_pmid_leads']!r})"
            )
    if _all_present("europe_pmc_records_returned", "new_pmid_leads") and "europe_pmc_unresolved_pmids" in unresolved:
        computed = counts["europe_pmc_records_returned"] + len(unresolved["europe_pmc_unresolved_pmids"])
        if computed != counts["new_pmid_leads"]:
            raise BundleBoundaryError(
                f"manifest counts arithmetic violation: europe_pmc_records_returned + "
                f"len(unresolved.europe_pmc_unresolved_pmids) ({computed!r}) does not equal "
                f"new_pmid_leads ({counts['new_pmid_leads']!r})"
            )
    if "pubmed_records_unresolved" in counts and "pubmed_missing_pmids" in unresolved:
        if len(unresolved["pubmed_missing_pmids"]) != counts["pubmed_records_unresolved"]:
            raise BundleBoundaryError(
                f"manifest counts arithmetic violation: len(unresolved.pubmed_missing_pmids) "
                f"({len(unresolved['pubmed_missing_pmids'])!r}) does not equal "
                f"counts.pubmed_records_unresolved ({counts['pubmed_records_unresolved']!r})"
            )
    if _all_present("pubmed_abstracts", "pubmed_records_returned") and counts["pubmed_abstracts"] > counts["pubmed_records_returned"]:
        raise BundleBoundaryError(
            f"manifest counts.pubmed_abstracts {counts['pubmed_abstracts']!r} exceeds "
            f"counts.pubmed_records_returned {counts['pubmed_records_returned']!r}"
        )
    if _all_present("pubmed_pmcids", "pubmed_records_returned") and counts["pubmed_pmcids"] > counts["pubmed_records_returned"]:
        raise BundleBoundaryError(
            f"manifest counts.pubmed_pmcids {counts['pubmed_pmcids']!r} exceeds "
            f"counts.pubmed_records_returned {counts['pubmed_records_returned']!r}"
        )
    if _all_present("pubmed_dois", "pubmed_records_returned") and counts["pubmed_dois"] > counts["pubmed_records_returned"]:
        raise BundleBoundaryError(
            f"manifest counts.pubmed_dois {counts['pubmed_dois']!r} exceeds "
            f"counts.pubmed_records_returned {counts['pubmed_records_returned']!r}"
        )
    if (
        _all_present("europe_pmc_abstracts", "europe_pmc_records_returned")
        and counts["europe_pmc_abstracts"] > counts["europe_pmc_records_returned"]
    ):
        raise BundleBoundaryError(
            f"manifest counts.europe_pmc_abstracts {counts['europe_pmc_abstracts']!r} exceeds "
            f"counts.europe_pmc_records_returned {counts['europe_pmc_records_returned']!r}"
        )
    if (
        _all_present("europe_pmc_pmcids", "europe_pmc_records_returned")
        and counts["europe_pmc_pmcids"] > counts["europe_pmc_records_returned"]
    ):
        raise BundleBoundaryError(
            f"manifest counts.europe_pmc_pmcids {counts['europe_pmc_pmcids']!r} exceeds "
            f"counts.europe_pmc_records_returned {counts['europe_pmc_records_returned']!r}"
        )
    if (
        _all_present("europe_pmc_open_access", "europe_pmc_records_returned")
        and counts["europe_pmc_open_access"] > counts["europe_pmc_records_returned"]
    ):
        raise BundleBoundaryError(
            f"manifest counts.europe_pmc_open_access {counts['europe_pmc_open_access']!r} "
            f"exceeds counts.europe_pmc_records_returned {counts['europe_pmc_records_returned']!r}"
        )
    if _all_present("fulltext_candidates", "licence_cc_by") and counts["fulltext_candidates"] > counts["licence_cc_by"]:
        raise BundleBoundaryError(
            f"manifest counts.fulltext_candidates {counts['fulltext_candidates']!r} exceeds "
            f"counts.licence_cc_by {counts['licence_cc_by']!r}"
        )
    if _all_present("article_index_rows", "new_pmid_leads") and counts["article_index_rows"] != counts["new_pmid_leads"]:
        raise BundleBoundaryError(
            f"manifest counts.article_index_rows {counts['article_index_rows']!r} does not "
            f"equal counts.new_pmid_leads {counts['new_pmid_leads']!r}"
        )
    if _all_present("licence_cc_by", "licence_cc_by_nc_nd", "licence_cc_by_nc_sa", "licence_absent", "europe_pmc_records_returned"):
        licence_axis_sum = (
            counts["licence_cc_by"]
            + counts["licence_cc_by_nc_nd"]
            + counts["licence_cc_by_nc_sa"]
            + counts["licence_absent"]
        )
        if licence_axis_sum != counts["europe_pmc_records_returned"]:
            raise BundleBoundaryError(
                f"manifest counts arithmetic violation: licence_cc_by + licence_cc_by_nc_nd + "
                f"licence_cc_by_nc_sa + licence_absent ({licence_axis_sum!r}) does not equal "
                f"europe_pmc_records_returned ({counts['europe_pmc_records_returned']!r})"
            )

    if licence_counts:
        licence_bucket_to_axis = {
            "CC BY": "licence_cc_by",
            "CC BY-NC-ND": "licence_cc_by_nc_nd",
            "CC BY-NC-SA": "licence_cc_by_nc_sa",
            "ABSENT": "licence_absent",
        }
        for bucket, axis in licence_bucket_to_axis.items():
            if bucket in licence_counts and axis in counts:
                if licence_counts[bucket] != counts[axis]:
                    raise BundleBoundaryError(
                        f"manifest licence_counts[{bucket!r}] ({licence_counts[bucket]!r}) does "
                        f"not equal counts[{axis!r}] ({counts[axis]!r})"
                    )
        if "europe_pmc_records_returned" in counts:
            licence_counts_sum = sum(licence_counts.values())
            if licence_counts_sum != counts["europe_pmc_records_returned"]:
                raise BundleBoundaryError(
                    f"manifest licence_counts values sum to {licence_counts_sum!r}, which does "
                    f"not equal counts.europe_pmc_records_returned "
                    f"{counts['europe_pmc_records_returned']!r}"
                )


def validate_manifest_hash(manifest: dict[str, Any]) -> None:
    """Strictly validate a ``raptor.external.r611q_literature_bundle.v1``
    manifest: this package's extended schema/consistency checks (see
    ``_validate_extended_manifest_schema`` and the module docstring)
    FIRST, then the manifest's own canonical ``content_hash`` (delegated
    to ``tsc2_sources.bundle.validate_manifest_hash``, which recomputes
    and compares it). Raises ``BundleBoundaryError``/
    ``BundleHashMismatchError`` on any violation."""
    _validate_extended_manifest_schema(manifest)
    _shared_validate_manifest_hash(manifest)


def build_bundle_manifest(
    *,
    bundle_id: str,
    created_at: str,
    query: dict[str, Any],
    artifacts: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    truncation: dict[str, Any],
    boundaries: dict[str, Any],
    baseline_hashes: dict[str, str] | None = None,
    source_response_hashes: dict[str, str] | None = None,
    licence_counts: dict[str, int] | None = None,
    unresolved: dict[str, list[str]] | None = None,
    counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Build and canonically self-hash a
    ``raptor.external.r611q_literature_bundle.v1`` manifest from
    already-verified artifact/source records (validated via the shared
    ``tsc2_sources.bundle`` schema/cross-reference checks). ``source_
    response_hashes`` is ALWAYS the exact derived mapping of one entry
    per artifact whose ``role`` is ``RAW_RESPONSE`` (keyed by
    ``source_id``) whenever at least one such artifact exists -- the
    optional ``source_response_hashes`` kwarg is NEVER merged/overridden
    into that derived mapping in that case (it is only ever consulted as
    a fallback when there is no RAW_RESPONSE artifact at all, alongside
    the final ``query``-hash fallback, so the field is never left empty).
    ``baseline_hashes`` defaults to a hash of ``query`` when the caller
    supplies none (guaranteeing the field is never empty even for a
    minimal manifest with no explicit baseline artifact). ``unresolved``
    defaults to ``{"pubmed_missing_pmids": [], "europe_pmc_unresolved_
    pmids": []}`` when the caller supplies none/an empty mapping -- the
    KEY set is never empty, even when every PMID resolved.
    ``fulltext_artifact_hashes`` is always DERIVED -- never caller-
    supplied -- as the sorted SHA-256 list of every artifact whose
    ``role`` is ``FULLTEXT_XML``. Raises ``BundleBoundaryError`` on a
    malformed record or a broken artifact/source cross-reference, and
    ``StatusVocabularyError`` if any source contains forbidden clinical/
    ACMG/classification vocabulary."""
    artifacts = list(artifacts)
    sources = list(sources)

    for artifact in artifacts:
        _validate_artifact_schema(artifact)
    for source in sources:
        _validate_source_schema(source)

    assert_no_forbidden_status_vocabulary(sources)
    _validate_cross_references(artifacts, sources)

    derived_source_response_hashes = {
        artifact["source_id"]: artifact["sha256"]
        for artifact in artifacts
        if artifact["role"] == _RAW_RESPONSE_ROLE
    }
    if not derived_source_response_hashes:
        # No RAW_RESPONSE artifact exists to derive from -- fall back to
        # the caller's optional mapping (never merged/updated once real
        # artifacts exist; see below), or a query hash as a last resort so
        # the field is never left empty.
        derived_source_response_hashes = dict(source_response_hashes) if source_response_hashes else {
            "query": _sha256_of(query)
        }

    derived_baseline_hashes = dict(baseline_hashes) if baseline_hashes else {}
    if not derived_baseline_hashes:
        derived_baseline_hashes = {"query": _sha256_of(query)}

    derived_unresolved = dict(unresolved) if unresolved else {}
    if not derived_unresolved:
        derived_unresolved = {"pubmed_missing_pmids": [], "europe_pmc_unresolved_pmids": []}

    fulltext_artifact_hashes = sorted(
        artifact["sha256"] for artifact in artifacts if artifact["role"] == _FULLTEXT_ROLE
    )

    merged_counts: dict[str, Any] = {"sources": len(sources), "artifacts": len(artifacts)}
    if counts:
        merged_counts.update(counts)
    merged_counts.setdefault("fulltext_candidates", len(fulltext_artifact_hashes))
    merged_counts["fulltext_acquired"] = len(fulltext_artifact_hashes)

    manifest: dict[str, Any] = {
        "schema": BUNDLE_MANIFEST_SCHEMA,
        "bundle_id": bundle_id,
        "created_at": created_at,
        "query": query,
        "artifacts": artifacts,
        "sources": sources,
        "counts": merged_counts,
        "truncation": truncation,
        "boundaries": boundaries,
        "baseline_hashes": derived_baseline_hashes,
        "source_response_hashes": derived_source_response_hashes,
        "licence_counts": dict(licence_counts) if licence_counts else {},
        "unresolved": derived_unresolved,
        "fulltext_artifact_hashes": fulltext_artifact_hashes,
    }
    manifest["content_hash"] = compute_bundle_content_hash(manifest)
    return manifest


def write_bundle_run(
    *,
    repo_root: Path,
    output_root: Path,
    run_name: str,
    manifest: dict[str, Any],
    artifact_payloads: dict[str, bytes],
) -> dict[str, Any]:
    """Validate ``manifest`` with this package's own strict ``validate_
    manifest_hash`` FIRST, then publish ``manifest`` and
    ``artifact_payloads`` to ``output_root/run_name`` -- external,
    create-only, atomic and symlink-safe (delegated to
    ``raptor.external.tsc2_sources.bundle.write_bundle_run``; see that
    function's docstring for the full create-only/atomic-publish
    contract). Returns ``{"run_dir", "manifest_path"}`` as ``Path``
    objects."""
    validate_manifest_hash(manifest)
    result = _shared_write_bundle_run(
        repo_root=repo_root,
        output_root=output_root,
        run_name=run_name,
        manifest=manifest,
        artifact_payloads=artifact_payloads,
    )
    return {
        "run_dir": Path(result["run_dir"]),
        "manifest_path": Path(result["manifest_path"]),
    }


def build_committed_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate ``manifest`` with this package's own strict ``validate_
    manifest_hash`` FIRST, then build the compact, aggregate-only
    committed summary: the manifest's own content hash, baseline/source-
    response hashes, counts, licence counts, ``unresolved_counts``
    (coerced from ``manifest["unresolved"]``'s PMID lists to their
    lengths -- the PMIDs themselves are never copied into the summary),
    the boundaries statement and the sorted full-text artifact hash list.
    This is a STRICT field-whitelist projection -- it never reads or
    copies a requested/final URL, a PMID, PMCID, DOI, title, abstract or
    full text; only the aggregate fields listed below are ever present."""
    validate_manifest_hash(manifest)
    unresolved_counts = {key: len(value) for key, value in manifest["unresolved"].items()}
    return {
        "schema": COMMITTED_SUMMARY_SCHEMA,
        "bundle_id": manifest["bundle_id"],
        "manifest_content_hash": manifest["content_hash"],
        "baseline_hashes": dict(manifest["baseline_hashes"]),
        "source_response_hashes": dict(manifest["source_response_hashes"]),
        "counts": dict(manifest["counts"]),
        "licence_counts": dict(manifest["licence_counts"]),
        "unresolved_counts": unresolved_counts,
        "boundaries": dict(manifest["boundaries"]),
        "fulltext_artifact_hashes": list(manifest["fulltext_artifact_hashes"]),
    }


__all__ = [
    "BUNDLE_MANIFEST_SCHEMA",
    "COMMITTED_SUMMARY_SCHEMA",
    "MANIFEST_FILENAME",
    "BundleBoundaryError",
    "BundleHashMismatchError",
    "StatusVocabularyError",
    "compute_bundle_content_hash",
    "validate_manifest_hash",
    "build_bundle_manifest",
    "write_bundle_run",
    "build_committed_summary",
]
