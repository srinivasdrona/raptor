#!/usr/bin/env python
"""Offline operator for the RAPTOR v2 R611Q literature acquisition-delta
review (``docs/project/specs/raptor-v2-r611q-literature-delta-review-v1.yaml``).

This script performs NO network I/O -- it only reads already-acquired,
pinned local bytes (the ``r611q_literature`` acquisition bundle, the
pinned RescueScreen baseline files, and the pinned Atlas expert-review
baseline files) and drives the pure, deterministic
``raptor.external.r611q_literature.delta_review`` module over them. It
never imports ``raptor.atlas``, ``raptor.rescuescreen``, ``raptor.scorer``,
``raptor.eval``, ``raptor.packet``, ``raptor.census``, ``raptor.kb`` or any
network-transport module.

Two explicit subcommands (see ``--help`` on either for their full flag
list):

``prepare``
    Re-verify every pinned acquisition/baseline/Atlas input hash from
    config, re-verify the acquisition manifest/artifacts/article index,
    deterministically scan each article's title, abstract and acquired
    JATS body for the fixed R611Q alias vocabulary, and emit a
    create-only external REVIEW-PREPARATION directory containing article
    dispositions, candidate spans and a review-record TEMPLATE (one
    template row per exact-alias candidate source, every scientific enum
    field left ``null`` -- human/model triage still required). This phase
    NEVER publishes the four final artifacts or the committed summary.

``publish``
    Repeat the same input verification/scanning as ``prepare``, then read
    a caller-supplied external review-record JSONL file (produced by
    completing the ``prepare`` template) and validate it covers EXACTLY
    the candidate sources with a valid representative ``candidate_id`` per
    source. Build the four final artifacts
    (``normalized/article-dispositions.jsonl``,
    ``normalized/candidate-spans.jsonl``, ``reviewed/review-records.jsonl``,
    ``reviewed/R611Q_LITERATURE_DELTA_ADDENDUM.md``) and a strict self-
    hashed manifest, publish them externally/create-only (manifest written
    last), then OPTIONALLY (``--write-summary``) write the exact
    configured aggregate-only committed summary create-only inside the
    repository. The rendered addendum may carry source identities/quotes
    externally, but it always states model-assisted/unaccepted triage,
    zero accepted claims, an unchanged Gate 8 state, and that this is not
    an ACMG/clinical/treatment authorization.

Every fallible step raises a typed, sanitized error (this script's own
``DeltaReviewOperatorError`` or the library's
``raptor.external.r611q_literature.delta_review.DeltaReviewError``) --
there is no broad ``except``/success fallback anywhere in this script.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from raptor.external.r611q_literature import delta_review as dr  # noqa: E402

DEFAULT_CONFIG = REPO_ROOT / "configs" / "external" / "r611q_literature_delta_review_v1.yaml"
DEFAULT_EXTERNAL_ROOT_ENV = "RAPTOR_R611Q_DELTA_REVIEW_ROOT"
DEFAULT_EXTERNAL_ROOT = Path.home() / "raptor-data" / "external" / "r611q-literature-delta-review"

_FULLTEXT_ACQUIRED_STATUS = "ACQUIRED_CC_BY"
_JATS_BODY_SURFACE = "acquired_cc_by_jats_body"
_TITLE_SURFACE = "title"
_ABSTRACT_SURFACE = "abstract"


class DeltaReviewOperatorError(RuntimeError):
    """Base error for this operator's own CLI/orchestration failures (file
    I/O, config shape, pinned-hash mismatch outside the library's own
    checks, or malformed caller-supplied review records) -- distinct from
    ``raptor.external.r611q_literature.delta_review.DeltaReviewError``,
    which is raised for every library-level contract violation."""


# ---------------------------------------------------------------------------
# Config / pinned-file loading
# ---------------------------------------------------------------------------


def load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.is_file():
        raise DeltaReviewOperatorError(f"config file not found: {config_path}")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise DeltaReviewOperatorError(f"config {config_path} did not parse to a mapping")
    return config


def resolve_external_root(config: dict[str, Any]) -> Path:
    env_name = config.get("output", {}).get("environment_variable", DEFAULT_EXTERNAL_ROOT_ENV)
    return Path(os.environ.get(env_name) or DEFAULT_EXTERNAL_ROOT).expanduser()


def _sha256_of_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_pinned_file(path: Path, *, expected_sha256: str, expected_byte_length: int, label: str) -> bytes:
    if not path.is_file():
        raise DeltaReviewOperatorError(f"{label} file not found: {path}")
    payload = path.read_bytes()
    if len(payload) != expected_byte_length:
        raise DeltaReviewOperatorError(
            f"{label} byte_length mismatch: expected {expected_byte_length!r}, observed "
            f"{len(payload)!r} ({path})"
        )
    observed = hashlib.sha256(payload).hexdigest()
    if observed.lower() != str(expected_sha256).lower():
        raise DeltaReviewOperatorError(
            f"{label} sha256 mismatch: expected {expected_sha256!r}, observed {observed!r} ({path})"
        )
    return payload


def verify_baseline_inputs(config: dict[str, Any], *, args: argparse.Namespace) -> dict[str, bytes]:
    """Re-verify every pinned RescueScreen/Atlas baseline file's bytes
    against the config pins. Returns the raw bytes read (never mutated,
    never rewritten -- these baseline artifacts are read-only input)."""
    rescuescreen = config["inputs"]["rescuescreen_baseline"]
    atlas = config["inputs"]["atlas_baseline"]

    source_manifest_bytes = _verify_pinned_file(
        args.rescuescreen_source_manifest,
        expected_sha256=rescuescreen["source_manifest"]["sha256"],
        expected_byte_length=rescuescreen["source_manifest"]["byte_length"],
        label="RescueScreen source manifest",
    )
    master_inventory_bytes = _verify_pinned_file(
        args.rescuescreen_master_inventory,
        expected_sha256=rescuescreen["master_source_inventory"]["sha256"],
        expected_byte_length=rescuescreen["master_source_inventory"]["byte_length"],
        label="RescueScreen master source inventory",
    )
    expert_packet_bytes = _verify_pinned_file(
        args.atlas_expert_packet,
        expected_sha256=atlas["expert_packet"]["sha256"],
        expected_byte_length=atlas["expert_packet"]["byte_length"],
        label="Atlas expert-review packet",
    )
    expert_form_bytes = _verify_pinned_file(
        args.atlas_expert_form,
        expected_sha256=atlas["expert_form"]["sha256"],
        expected_byte_length=atlas["expert_form"]["byte_length"],
        label="Atlas expert-review form",
    )
    return {
        "rescuescreen_source_manifest": source_manifest_bytes,
        "rescuescreen_master_inventory": master_inventory_bytes,
        "atlas_expert_packet": expert_packet_bytes,
        "atlas_expert_form": expert_form_bytes,
    }


def _collect_recursive(obj: Any, keys: frozenset[str], out: set[str]) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in keys and isinstance(value, str) and value:
                out.add(value)
            _collect_recursive(value, keys, out)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _collect_recursive(item, keys, out)


def derive_baseline_source_ids(master_inventory_bytes: bytes) -> set[str]:
    """Best-effort, schema-tolerant extraction of the pinned RescueScreen
    master inventory's own source identities (as ``PMID:<pmid>`` strings,
    matching this package's own review-record ``source_id`` convention),
    used ONLY to reject a source-identity collision between a delta-review
    candidate and the existing baseline inventory. Never rewrites, edits
    or republishes any part of the master inventory itself. Raises
    ``DeltaReviewOperatorError`` if the inventory contains no recognizable
    pmid identifier at all (fails loud rather than silently proceeding
    with an empty baseline set, which would defeat the collision guard)."""
    try:
        payload = json.loads(master_inventory_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeltaReviewOperatorError(f"RescueScreen master inventory is not valid UTF-8 JSON: {exc}") from exc

    raw_pmids: set[str] = set()
    _collect_recursive(payload, frozenset({"pmid", "PMID"}), raw_pmids)
    source_ids = {f"PMID:{pmid}" for pmid in raw_pmids}
    if not source_ids:
        raise DeltaReviewOperatorError(
            "RescueScreen master inventory did not yield any recognizable pmid identifier; "
            "refusing to proceed with an empty baseline collision set"
        )
    return source_ids


def derive_proposition_vocabulary(master_inventory_bytes: bytes) -> set[str]:
    """Best-effort, schema-tolerant extraction of the pinned RescueScreen
    master inventory's own proposition-identifier vocabulary. Raises
    ``DeltaReviewOperatorError`` if none is found (fails loud rather than
    silently allowing every ``proposition_ids`` value through)."""
    try:
        payload = json.loads(master_inventory_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeltaReviewOperatorError(f"RescueScreen master inventory is not valid UTF-8 JSON: {exc}") from exc

    propositions: set[str] = set()
    _collect_recursive(payload, frozenset({"proposition_id", "proposition_ids", "propositions"}), propositions)
    if not propositions:
        raise DeltaReviewOperatorError(
            "RescueScreen master inventory did not yield any recognizable proposition "
            "identifier; refusing to proceed with an empty proposition vocabulary"
        )
    return propositions


# ---------------------------------------------------------------------------
# Acquisition bundle reading / deterministic scanning
# ---------------------------------------------------------------------------


def read_article_index_rows(manifest: dict[str, Any], bundle_root: Path, article_index_relative_path: str) -> list[dict[str, Any]]:
    path = bundle_root / article_index_relative_path
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or set(row) != dr.ARTICLE_INDEX_FIELDS:
            raise DeltaReviewOperatorError(f"article index row does not have the exact expected fields: {row!r}")
        rows.append(row)
    return rows


def _artifact_relative_path_by_id(manifest: dict[str, Any]) -> dict[str, str]:
    return {artifact["artifact_id"]: artifact["relative_path"] for artifact in manifest["artifacts"]}


def _artifact_sha256_by_relative_path(manifest: dict[str, Any]) -> dict[str, str]:
    return {artifact["relative_path"]: artifact["sha256"] for artifact in manifest["artifacts"]}


def scan_acquisition_bundle(
    *, manifest: dict[str, Any], bundle_root: Path, article_index_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Deterministically scan every article-index row's title, abstract
    and (when acquired) JATS full-text body for the fixed R611Q alias
    vocabulary. Returns per-row disposition/candidate-span material plus
    the raw artifact sha256/joined-surface-text maps
    ``validate_candidate_spans`` needs. Never performs network I/O -- every
    byte scanned here is already present under ``bundle_root``."""
    relpath_by_artifact_id = _artifact_relative_path_by_id(manifest)
    artifact_sha256_by_relpath = _artifact_sha256_by_relative_path(manifest)

    dispositions: list[dict[str, Any]] = []
    candidate_spans: list[dict[str, Any]] = []
    candidate_source_ids: set[str] = set()
    joined_surface_text_by_artifact: dict[str, str] = {}

    for row in article_index_rows:
        article_identity = {"pmid": row["pmid"], "pmcid": row["pmcid"], "doi": row["doi"]}
        source_id = f"PMID:{row['pmid']}"

        title_matches = dr.match_aliases(row.get("title") or "")
        abstract_matches = dr.match_aliases(row.get("abstract") or "")

        body_blocks: list[dict[str, Any]] = []
        fulltext_available = row.get("fulltext_status") == _FULLTEXT_ACQUIRED_STATUS and row.get("fulltext_artifact_id")
        source_artifact_id = None
        if fulltext_available:
            source_artifact_id = relpath_by_artifact_id.get(row["fulltext_artifact_id"])
            if source_artifact_id is None:
                raise DeltaReviewOperatorError(
                    f"article {row['pmid']!r} references unknown fulltext_artifact_id "
                    f"{row['fulltext_artifact_id']!r}"
                )
            xml_path = bundle_root / source_artifact_id
            if not xml_path.is_file():
                raise DeltaReviewOperatorError(f"acquired JATS full text missing on disk: {xml_path}")
            xml_text = xml_path.read_text(encoding="utf-8")
            extracted = dr.extract_jats_blocks(xml_text=xml_text)
            joined_surface_text_by_artifact[source_artifact_id] = extracted["joined_text"]
            body_blocks = extracted["blocks"]

        matched_anywhere = bool(title_matches) or bool(abstract_matches) or bool(body_blocks)
        has_title_or_abstract_text = bool(row.get("title")) or bool(row.get("abstract"))

        if fulltext_available:
            disposition = "EXACT_ALIAS_CANDIDATE" if matched_anywhere else "NO_EXACT_ALIAS_IN_AVAILABLE_TEXT"
        elif matched_anywhere:
            disposition = "EXACT_ALIAS_CANDIDATE"
        elif has_title_or_abstract_text:
            disposition = "NO_EXACT_ALIAS_IN_AVAILABLE_TEXT"
        else:
            disposition = "SOURCE_TEXT_UNAVAILABLE"

        dispositions.append({"article_identity": article_identity, "disposition": disposition})

        if disposition != "EXACT_ALIAS_CANDIDATE":
            continue
        candidate_source_ids.add(source_id)

        for surface, matches, surface_text in (
            (_TITLE_SURFACE, title_matches, row.get("title")),
            (_ABSTRACT_SURFACE, abstract_matches, row.get("abstract")),
        ):
            if not matches:
                continue
            normalized = dr._normalize_text(surface_text or "")
            joined_surface_text_by_artifact.setdefault(f"{surface}:{source_id}", normalized)
            span = {
                "schema": dr.CANDIDATE_SPAN_SCHEMA,
                "candidate_id": dr._candidate_id(article_identity, surface, 0),
                "article_identity": article_identity,
                "source_artifact_id": f"{surface}:{source_id}",
                "source_artifact_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
                "surface": surface,
                "block_index": 0,
                "block_tag": surface,
                "context": {"section_title_path": [surface]},
                "locator": f"text-char:0:{len(normalized)}",
                "exact_quote": normalized,
                "exact_quote_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
                "matched_aliases": matches,
                "review_state": "PROPOSED_UNACCEPTED",
            }
            artifact_sha256_by_relpath.setdefault(span["source_artifact_id"], span["source_artifact_sha256"])
            candidate_spans.append(span)

        if source_artifact_id is not None:
            for block in body_blocks:
                span = {
                    "schema": dr.CANDIDATE_SPAN_SCHEMA,
                    "candidate_id": dr._candidate_id(article_identity, _JATS_BODY_SURFACE, block["block_index"]),
                    "article_identity": article_identity,
                    "source_artifact_id": source_artifact_id,
                    "source_artifact_sha256": artifact_sha256_by_relpath[source_artifact_id],
                    "surface": _JATS_BODY_SURFACE,
                    "block_index": block["block_index"],
                    "block_tag": block["block_tag"],
                    "context": block["context"],
                    "locator": block["locator"],
                    "exact_quote": block["text"],
                    "exact_quote_sha256": hashlib.sha256(block["text"].encode("utf-8")).hexdigest(),
                    "matched_aliases": block["matched_aliases"],
                    "review_state": "PROPOSED_UNACCEPTED",
                }
                candidate_spans.append(span)

    return {
        "dispositions": dispositions,
        "candidate_spans": candidate_spans,
        "candidate_source_ids": candidate_source_ids,
        "source_artifact_hashes": artifact_sha256_by_relpath,
        "joined_surface_text_by_artifact": joined_surface_text_by_artifact,
    }


def representative_candidate_ids(candidate_spans: list[dict[str, Any]]) -> dict[str, str]:
    """One deterministic representative ``candidate_id`` per source
    (``PMID:<pmid>``): the lexicographically smallest candidate id among
    that source's spans, so the choice never depends on scan/iteration
    order."""
    by_source: dict[str, list[str]] = {}
    for span in candidate_spans:
        source_id = f"PMID:{span['article_identity']['pmid']}"
        by_source.setdefault(source_id, []).append(span["candidate_id"])
    return {source_id: sorted(ids)[0] for source_id, ids in by_source.items()}


def build_review_record_template(
    *, candidate_source_ids: set[str], candidate_spans: list[dict[str, Any]], article_identity_by_source: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Build one review-record TEMPLATE row per candidate source (spec's
    ``supervised_delta_review.one_record_per``), every scientific enum
    field left ``None`` -- human/model triage is still required for every
    one of them. Never itself assigns a source role, primary-result
    state, baseline relation, delta value or proposition id."""
    representative = representative_candidate_ids(candidate_spans)
    template: list[dict[str, Any]] = []
    for source_id in sorted(candidate_source_ids):
        template.append(
            {
                "schema": dr.REVIEW_RECORD_SCHEMA,
                "source_id": source_id,
                "article_identity": article_identity_by_source[source_id],
                "candidate_id": representative[source_id],
                "source_role": None,
                "primary_result_state": None,
                "baseline_relation": None,
                "baseline_claim_id": None,
                "delta_value": None,
                "proposition_ids": [],
                "context": {field: None for field in dr.REQUIRED_CONTEXT_FIELDS},
                "review_kind": "MODEL_ASSISTED_SOURCE_TRIAGE",
                "acceptance_state": "PROPOSED_UNACCEPTED",
                "human_gate_8_effect": "NONE",
                "claim_change": "NONE",
                "gate_8_change": "NONE",
            }
        )
    return template


# ---------------------------------------------------------------------------
# Addendum rendering
# ---------------------------------------------------------------------------


def render_addendum(*, review_records: list[dict[str, Any]], candidate_spans_by_id: dict[str, dict[str, Any]]) -> str:
    lines = [
        "# R611Q Literature Delta-Review Addendum",
        "",
        "**Model-assisted source triage -- NOT a qualified human review.**",
        "",
        "- Acceptance state: every record below is `PROPOSED_UNACCEPTED`.",
        "- Accepted claims from this addendum: 0.",
        "- Gate 8 state: unchanged (`BLOCKED_HUMAN_REVIEW`); `human_gate_8_effect` is always `NONE`.",
        "- This addendum assigns no ACMG criterion, no clinical significance, no evidence-strength",
        "  classification and makes no treatment recommendation.",
        "",
    ]
    for record in sorted(review_records, key=lambda r: r["source_id"]):
        span = candidate_spans_by_id.get(record["candidate_id"])
        lines.append(f"## {record['source_id']}")
        lines.append("")
        lines.append(f"- source_role: `{record['source_role']}`")
        lines.append(f"- primary_result_state: `{record['primary_result_state']}`")
        lines.append(f"- baseline_relation: `{record['baseline_relation']}` (claim: `{record['baseline_claim_id']}`)")
        lines.append(f"- delta_value: `{record['delta_value']}`")
        lines.append(f"- proposition_ids: `{record['proposition_ids']}`")
        if span is not None:
            lines.append(f"- representative quote: \"{span['exact_quote']}\"")
            lines.append(f"- locator: `{span['locator']}`")
        lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Shared CLI plumbing
# ---------------------------------------------------------------------------


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help=f"delta-review YAML config (default: {DEFAULT_CONFIG})")
    parser.add_argument("--acquisition-bundle-root", type=Path, required=True, help="root of the already-published r611q_literature acquisition bundle (contains bundle_manifest.json)")
    parser.add_argument("--rescuescreen-source-manifest", type=Path, required=True, help="path to the pinned RescueScreen discovery-shelf source manifest JSON")
    parser.add_argument("--rescuescreen-master-inventory", type=Path, required=True, help="path to the pinned RescueScreen master source inventory JSON")
    parser.add_argument("--atlas-expert-packet", type=Path, required=True, help="path to the pinned Atlas expert-review packet JSON")
    parser.add_argument("--atlas-expert-form", type=Path, required=True, help="path to the pinned Atlas expert-review form JSON")
    parser.add_argument("--output-root", type=Path, default=None, help=f"external run root (default: ${DEFAULT_EXTERNAL_ROOT_ENV} or {DEFAULT_EXTERNAL_ROOT})")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT, help="repository root (the external bundle must never resolve inside it)")


def _verify_inputs_and_scan(config: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    acquisition_pin = config["inputs"]["acquisition_bundle"]
    manifest_path = args.acquisition_bundle_root / dr.MANIFEST_FILENAME
    validated = dr.validate_acquisition_manifest(
        manifest_path=manifest_path,
        bundle_root=args.acquisition_bundle_root,
        expected_manifest_content_hash=acquisition_pin["manifest_content_hash"],
        expected_manifest_file_sha256=acquisition_pin["manifest_file_sha256"],
        expected_manifest_byte_length=acquisition_pin["manifest_byte_length"],
        expected_article_index=acquisition_pin["article_index"],
    )
    manifest = validated["manifest"]

    baseline_bytes = verify_baseline_inputs(config, args=args)

    article_index_rows = read_article_index_rows(
        manifest, args.acquisition_bundle_root, acquisition_pin["article_index"]["relative_path"]
    )

    scan = scan_acquisition_bundle(manifest=manifest, bundle_root=args.acquisition_bundle_root, article_index_rows=article_index_rows)

    dr.validate_article_dispositions(article_index_rows=article_index_rows, dispositions=scan["dispositions"])
    dr.validate_candidate_spans(
        candidate_spans=scan["candidate_spans"],
        article_index_rows=article_index_rows,
        source_artifact_hashes=scan["source_artifact_hashes"],
        joined_surface_text_by_artifact=scan["joined_surface_text_by_artifact"],
    )

    return {
        "manifest": manifest,
        "article_index_rows": article_index_rows,
        "baseline_bytes": baseline_bytes,
        **scan,
    }


# ---------------------------------------------------------------------------
# prepare
# ---------------------------------------------------------------------------


def run_prepare(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    prepared = _verify_inputs_and_scan(config, args)

    article_identity_by_source = {
        f"PMID:{row['pmid']}": {"pmid": row["pmid"], "pmcid": row["pmcid"], "doi": row["doi"]}
        for row in prepared["article_index_rows"]
    }
    template = build_review_record_template(
        candidate_source_ids=prepared["candidate_source_ids"],
        candidate_spans=prepared["candidate_spans"],
        article_identity_by_source=article_identity_by_source,
    )

    disposition_bytes = "".join(json.dumps(d, sort_keys=True, separators=(",", ":")) + "\n" for d in prepared["dispositions"]).encode("utf-8")
    candidate_bytes = "".join(json.dumps(s, sort_keys=True, separators=(",", ":")) + "\n" for s in prepared["candidate_spans"]).encode("utf-8")
    template_bytes = "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in template).encode("utf-8")

    artifact_payloads = {
        "normalized/article-dispositions.jsonl": disposition_bytes,
        "normalized/candidate-spans.jsonl": candidate_bytes,
        "reviewed/review-records.jsonl": template_bytes,
    }
    artifacts = [
        {"relative_path": rel, "byte_length": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        for rel, payload in artifact_payloads.items()
    ]
    manifest: dict[str, Any] = {
        "schema": dr.DELTA_PREPARATION_MANIFEST_SCHEMA,
        "bundle_id": f"{config['bundle_id']}-prepare",
        "artifacts": artifacts,
        "counts": {
            "article_rows": len(prepared["article_index_rows"]),
            "candidate_source_count": len(prepared["candidate_source_ids"]),
            "candidate_span_count": len(prepared["candidate_spans"]),
            "review_record_template_count": len(template),
        },
        "content_hash": "",
    }
    manifest["content_hash"] = dr.compute_manifest_content_hash(manifest)

    output_root = args.output_root or resolve_external_root(config)
    run_name = args.run_name or f"{config['run_name']}-prepare"
    result = dr.write_delta_bundle(
        repo_root=args.repo_root,
        output_root=output_root,
        run_name=run_name,
        manifest=manifest,
        artifact_payloads=artifact_payloads,
    )
    print(f"review-preparation directory written: {result['run_dir']}")
    print(
        f"article_rows={manifest['counts']['article_rows']} "
        f"candidate_sources={manifest['counts']['candidate_source_count']} "
        f"candidate_spans={manifest['counts']['candidate_span_count']}"
    )
    return 0


# ---------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------


def _read_review_records_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise DeltaReviewOperatorError(f"external review-record JSONL file not found: {path}")
    records: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DeltaReviewOperatorError(f"review-record JSONL line {lineno} is not valid JSON: {exc}") from exc
        if not isinstance(record, dict):
            raise DeltaReviewOperatorError(f"review-record JSONL line {lineno} is not a JSON object")
        records.append(record)
    return records


def run_publish(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    prepared = _verify_inputs_and_scan(config, args)

    baseline_source_ids = derive_baseline_source_ids(prepared["baseline_bytes"]["rescuescreen_master_inventory"])
    proposition_vocabulary = derive_proposition_vocabulary(prepared["baseline_bytes"]["rescuescreen_master_inventory"])
    allowed_claim_ids = set(config["supervised_delta_review"]["baseline_relation"]["claims"])

    review_records = _read_review_records_jsonl(args.review_records)

    representative = representative_candidate_ids(prepared["candidate_spans"])
    valid_candidate_ids_by_source: dict[str, set[str]] = {}
    for span in prepared["candidate_spans"]:
        source_id = f"PMID:{span['article_identity']['pmid']}"
        valid_candidate_ids_by_source.setdefault(source_id, set()).add(span["candidate_id"])
    for record in review_records:
        source_id = record.get("source_id")
        candidate_id = record.get("candidate_id")
        valid_ids = valid_candidate_ids_by_source.get(source_id, set())
        if candidate_id not in valid_ids:
            raise DeltaReviewOperatorError(
                f"review record for {source_id!r} references candidate_id {candidate_id!r}, which "
                f"is not one of that source's own candidate spans {sorted(valid_ids)!r}"
            )

    dr.validate_review_records(
        review_records=review_records,
        candidate_source_ids=prepared["candidate_source_ids"],
        baseline_source_ids=baseline_source_ids,
        proposition_vocabulary=proposition_vocabulary,
        allowed_claim_ids=allowed_claim_ids,
    )

    candidate_spans_by_id = {span["candidate_id"]: span for span in prepared["candidate_spans"]}
    addendum_text = render_addendum(review_records=review_records, candidate_spans_by_id=candidate_spans_by_id)

    source_role_counts = {role: 0 for role in sorted(dr.SOURCE_ROLES)}
    delta_value_counts = {value: 0 for value in sorted(dr.DELTA_VALUES)}
    baseline_relation_counts = {relation: 0 for relation in sorted(dr.BASELINE_RELATIONS)}
    for record in review_records:
        source_role_counts[record["source_role"]] += 1
        delta_value_counts[record["delta_value"]] += 1
        baseline_relation_counts[record["baseline_relation"]] += 1

    disposition_bytes = "".join(json.dumps(d, sort_keys=True, separators=(",", ":")) + "\n" for d in prepared["dispositions"]).encode("utf-8")
    candidate_bytes = "".join(json.dumps(s, sort_keys=True, separators=(",", ":")) + "\n" for s in prepared["candidate_spans"]).encode("utf-8")
    review_bytes = "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in review_records).encode("utf-8")
    addendum_bytes = addendum_text.encode("utf-8")

    artifact_payloads = {
        "normalized/article-dispositions.jsonl": disposition_bytes,
        "normalized/candidate-spans.jsonl": candidate_bytes,
        "reviewed/review-records.jsonl": review_bytes,
        "reviewed/R611Q_LITERATURE_DELTA_ADDENDUM.md": addendum_bytes,
    }
    artifacts = [
        {"relative_path": rel, "byte_length": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        for rel, payload in artifact_payloads.items()
    ]

    acquisition_pin = config["inputs"]["acquisition_bundle"]
    rescuescreen_pin = config["inputs"]["rescuescreen_baseline"]
    atlas_pin = config["inputs"]["atlas_baseline"]

    manifest: dict[str, Any] = {
        "schema": dr.DELTA_BUNDLE_MANIFEST_SCHEMA,
        "bundle_id": config["bundle_id"],
        "artifacts": artifacts,
        "input_hashes": {
            "acquisition_manifest_content_hash": acquisition_pin["manifest_content_hash"],
            "acquisition_manifest_file_sha256": acquisition_pin["manifest_file_sha256"],
            "rescuescreen_source_manifest_sha256": rescuescreen_pin["source_manifest"]["sha256"],
            "rescuescreen_master_inventory_sha256": rescuescreen_pin["master_source_inventory"]["sha256"],
            "atlas_expert_packet_sha256": atlas_pin["expert_packet"]["sha256"],
            "atlas_expert_form_sha256": atlas_pin["expert_form"]["sha256"],
        },
        "counts": {
            "article_rows": len(prepared["article_index_rows"]),
            "exact_alias_candidate_sources": len(prepared["candidate_source_ids"]),
            "title_or_abstract_candidate_sources": sum(
                1
                for span in prepared["candidate_spans"]
                if span["surface"] in (_TITLE_SURFACE, _ABSTRACT_SURFACE)
            ),
            "fulltext_body_candidate_sources": len(
                {
                    f"PMID:{span['article_identity']['pmid']}"
                    for span in prepared["candidate_spans"]
                    if span["surface"] == _JATS_BODY_SURFACE
                }
            ),
            "acquired_fulltexts_without_exact_alias": sum(
                1
                for row in prepared["article_index_rows"]
                if row.get("fulltext_status") == _FULLTEXT_ACQUIRED_STATUS
                and f"PMID:{row['pmid']}" not in prepared["candidate_source_ids"]
            ),
            "sources_without_acquired_fulltext": sum(
                1 for row in prepared["article_index_rows"] if row.get("fulltext_status") != _FULLTEXT_ACQUIRED_STATUS
            ),
            "candidate_span_count": len(prepared["candidate_spans"]),
            "review_record_count": len(review_records),
            "accepted_claims": 0,
        },
        "source_role_counts": source_role_counts,
        "delta_value_counts": delta_value_counts,
        "baseline_relation_counts": baseline_relation_counts,
        "boundaries": {
            "existing_package_mutation": "forbidden",
            "accepted_claims": 0,
            "atlas_gate_8_change": "forbidden",
            "clinical_use": "forbidden",
            "evidence_strength_use": "forbidden",
            "ps3_bs3_use": "forbidden",
            "treatment_recommendation": "forbidden",
        },
        "content_hash": "",
    }
    manifest["content_hash"] = dr.compute_manifest_content_hash(manifest)

    output_root = args.output_root or resolve_external_root(config)
    run_name = args.run_name or config["run_name"]
    result = dr.write_delta_bundle(
        repo_root=args.repo_root,
        output_root=output_root,
        run_name=run_name,
        manifest=manifest,
        artifact_payloads=artifact_payloads,
    )
    print(f"delta-review bundle written: {result['run_dir']}")
    print(f"content_hash={manifest['content_hash']}")

    if args.write_summary:
        summary = dr.build_committed_summary(manifest)
        summary_path = args.repo_root / config["committed_summary_path"]
        payload = (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode("utf-8")
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        with open(str(summary_path), "xb") as handle:
            handle.write(payload)
        print(f"committed summary written: {summary_path}")

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare", help="emit the create-only external review-preparation directory")
    _add_common_arguments(prepare_parser)
    prepare_parser.add_argument("--run-name", default=None, help="external run directory name (default: '<config run_name>-prepare')")
    prepare_parser.set_defaults(func=run_prepare)

    publish_parser = subparsers.add_parser("publish", help="validate completed review records and publish the final delta-review bundle")
    _add_common_arguments(publish_parser)
    publish_parser.add_argument("--review-records", type=Path, required=True, help="path to the caller-supplied completed external review-record JSONL file")
    publish_parser.add_argument("--run-name", default=None, help="external run directory name (default: config run_name)")
    publish_parser.add_argument(
        "--write-summary", action="store_true",
        help="also write the exact configured aggregate-only committed summary create-only inside the repository",
    )
    publish_parser.set_defaults(func=run_publish)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        return args.func(args)
    except (DeltaReviewOperatorError, dr.DeltaReviewError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
