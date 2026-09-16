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
import re
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


def _decode_master_inventory_payload(master_inventory_bytes: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(master_inventory_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeltaReviewOperatorError(f"RescueScreen master inventory is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise DeltaReviewOperatorError("RescueScreen master inventory must decode to a JSON object")
    return payload


def _extract_master_inventory_source_ids(payload: dict[str, Any]) -> set[str]:
    """Strictly extract the master inventory's own publication source ids
    from its TOP-LEVEL ``publications`` list ONLY -- never from any other
    or nested key. Each publication entry must carry a unique, non-blank
    ``source_id`` string (PMID- or DOI-based; DOI-only entries are
    included exactly as recorded). When a publication also carries an
    ``identifiers`` mapping with a ``pmid`` entry, that pmid MUST be
    consistent with the entry's own ``source_id`` (``PMID:<pmid>``) -- the
    only cross-check performed; no other nested field (e.g. a ``notes``
    sibling key) is ever read. Raises ``DeltaReviewOperatorError`` on any
    malformed shape."""
    publications = payload.get("publications")
    if not isinstance(publications, list):
        raise DeltaReviewOperatorError(
            f"master inventory 'publications' must be a list matching its schema, found "
            f"{type(publications).__name__}"
        )
    source_ids: set[str] = set()
    for entry in publications:
        if not isinstance(entry, dict):
            raise DeltaReviewOperatorError(f"master inventory publication entry must be a mapping: {entry!r}")
        source_id = entry.get("source_id")
        if not isinstance(source_id, str) or not source_id.strip():
            raise DeltaReviewOperatorError(
                f"master inventory publication entry has a blank/non-string source_id: {entry!r}"
            )
        if source_id in source_ids:
            raise DeltaReviewOperatorError(
                f"master inventory has a duplicate source_id across publications: {source_id!r}"
            )
        identifiers = entry.get("identifiers")
        if identifiers is not None:
            if not isinstance(identifiers, dict):
                raise DeltaReviewOperatorError(
                    f"master inventory publication {source_id!r} 'identifiers' must be a mapping: "
                    f"{identifiers!r}"
                )
            pmid = identifiers.get("pmid")
            if pmid is not None:
                expected_source_id = f"PMID:{pmid}"
                if source_id != expected_source_id:
                    raise DeltaReviewOperatorError(
                        "master inventory publication pmid identifier is inconsistent with its "
                        f"own source_id: identifiers.pmid={pmid!r} implies source_id "
                        f"{expected_source_id!r}, found {source_id!r}"
                    )
        source_ids.add(source_id)
    return source_ids


def _extract_master_inventory_proposition_vocabulary(payload: dict[str, Any]) -> set[str]:
    """Strictly extract the master inventory's proposition-identifier
    vocabulary from its TOP-LEVEL ``proposition_vocabulary`` mapping ONLY
    (keys only -- the description values are never treated as
    identifiers, and no nested/other key is ever harvested). Raises
    ``DeltaReviewOperatorError`` on any malformed shape."""
    vocabulary = payload.get("proposition_vocabulary")
    if not isinstance(vocabulary, dict):
        raise DeltaReviewOperatorError(
            f"master inventory 'proposition_vocabulary' must be a mapping matching its schema, "
            f"found {type(vocabulary).__name__}"
        )
    proposition_ids: set[str] = set()
    for key, value in vocabulary.items():
        if not isinstance(key, str) or not key.strip():
            raise DeltaReviewOperatorError(
                f"master inventory proposition_vocabulary has a blank/non-string identifier: {key!r}"
            )
        if not isinstance(value, str):
            raise DeltaReviewOperatorError(
                f"master inventory proposition_vocabulary[{key!r}] must be a string description, "
                f"found {type(value).__name__}"
            )
        proposition_ids.add(key)
    return proposition_ids


def derive_baseline_source_ids(master_inventory_bytes: bytes) -> set[str]:
    """Strictly parse the pinned RescueScreen master inventory (a single
    decode/validate pass -- see ``_extract_master_inventory_source_ids``)
    and return its exact publication source-id set, used ONLY to reject a
    source-identity collision between a delta-review candidate and the
    existing baseline inventory. Never rewrites, edits or republishes any
    part of the master inventory itself. Wraps the same strict extraction
    ``parse_master_inventory`` uses, for call-site compatibility with
    callers that do not know the expected publication count up front."""
    payload = _decode_master_inventory_payload(master_inventory_bytes)
    return _extract_master_inventory_source_ids(payload)


def derive_proposition_vocabulary(master_inventory_bytes: bytes) -> set[str]:
    """Strictly parse the pinned RescueScreen master inventory (a single
    decode/validate pass -- see
    ``_extract_master_inventory_proposition_vocabulary``) and return its
    exact top-level proposition-vocabulary key set."""
    payload = _decode_master_inventory_payload(master_inventory_bytes)
    return _extract_master_inventory_proposition_vocabulary(payload)


def parse_master_inventory(*, master_inventory_bytes: bytes, expected_publications: int) -> dict[str, Any]:
    """The strict, public, single-parse master-inventory reader: decodes
    ``master_inventory_bytes`` exactly once, enforces its ``publications``
    list has EXACTLY ``expected_publications`` entries (a pinned-count
    structural-drift guard beyond the acquisition manifest's own byte-hash
    pin), and returns ``{"source_ids": set[str], "proposition_vocabulary":
    set[str]}`` via the same strict extraction ``derive_baseline_source_
    ids``/``derive_proposition_vocabulary`` wrap. Raises
    ``DeltaReviewOperatorError`` on any malformed shape or a publication-
    count mismatch."""
    payload = _decode_master_inventory_payload(master_inventory_bytes)
    publications = payload.get("publications")
    if not isinstance(publications, list):
        raise DeltaReviewOperatorError(
            f"master inventory 'publications' must be a list matching its schema, found "
            f"{type(publications).__name__}"
        )
    if len(publications) != expected_publications:
        raise DeltaReviewOperatorError(
            f"master inventory publication count mismatch: expected_publications="
            f"{expected_publications!r}, found {len(publications)!r}"
        )
    return {
        "source_ids": _extract_master_inventory_source_ids(payload),
        "proposition_vocabulary": _extract_master_inventory_proposition_vocabulary(payload),
    }


# ---------------------------------------------------------------------------
# Acquisition bundle reading / deterministic scanning
# ---------------------------------------------------------------------------


_CANONICAL_PMID_PATTERN = re.compile(r"^[1-9][0-9]*$")


def read_article_index_rows(
    manifest: dict[str, Any], bundle_root: Path, article_index_relative_path: str
) -> list[dict[str, Any]]:
    """Strictly parse and structurally validate every article-index row
    BEFORE any deterministic scanning begins: exact field set, an exact
    article schema value, a canonical (non-zero-padded, positive)
    numeric-string ``pmid``, scalar (string-or-null) ``pmcid``/``doi``
    identity fields, no duplicate ``pmid``, and rows in strictly ascending
    numeric ``pmid`` order. This catches structural drift even when the
    acquisition manifest's own pinned hashes still recompute correctly (a
    byte-identical file can still fail this stricter structural contract).
    ``manifest`` is accepted for interface symmetry with the acquisition-
    manifest validation step but is not itself read here. Raises
    ``DeltaReviewOperatorError`` on any violation."""
    path = bundle_root / article_index_relative_path
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or set(row) != dr.ARTICLE_INDEX_FIELDS:
            raise DeltaReviewOperatorError(f"article index row does not have the exact expected fields: {row!r}")
        if row.get("schema") != dr.ARTICLE_INDEX_SCHEMA:
            raise DeltaReviewOperatorError(
                f"article index row schema does not match the expected article schema "
                f"{dr.ARTICLE_INDEX_SCHEMA!r}: {row.get('schema')!r}"
            )
        pmid = row.get("pmid")
        if not isinstance(pmid, str) or not _CANONICAL_PMID_PATTERN.match(pmid):
            raise DeltaReviewOperatorError(
                f"article index row pmid is not a canonical positive-integer pmid string: {pmid!r}"
            )
        for field in ("pmcid", "doi"):
            value = row.get(field)
            if value is not None and not isinstance(value, str):
                raise DeltaReviewOperatorError(
                    f"article index row identity field {field!r} must be a scalar string or null, "
                    f"found {type(value).__name__}: {value!r}"
                )
        rows.append(row)

    seen_pmids: set[str] = set()
    for row in rows:
        pmid = row["pmid"]
        if pmid in seen_pmids:
            raise DeltaReviewOperatorError(f"article index has a duplicate pmid; rows must be unique: {pmid!r}")
        seen_pmids.add(pmid)

    numeric_pmids = [int(row["pmid"]) for row in rows]
    if numeric_pmids != sorted(numeric_pmids):
        raise DeltaReviewOperatorError(
            "article index rows are not sorted by pmid in strictly ascending numeric order"
        )

    return rows


def _validate_fulltext_artifact_identities(article_index_rows: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    """Cross-check every ``fulltext_status == ACQUIRED_CC_BY`` row's
    ``fulltext_artifact_id`` against the acquisition manifest's own
    artifact identity BEFORE any scanning begins: the referenced artifact
    must exist; when the row carries a pmcid, the artifact's own
    ``relative_path`` must contain that pmcid (relative-path
    consistency); and, ONLY when the artifact's own ``source_id`` already
    encodes a per-article pmcid identity (``pmcid:<PMCID>`` -- some
    acquisition-bundle generations instead use a generic, role-only
    ``source_id`` such as ``fulltext`` for every full-text artifact, which
    carries no per-article identity to check beyond existence and the
    byte/hash verification ``validate_acquisition_manifest`` already
    performs), that ``source_id`` must also agree with the row's own
    pmcid. This never trusts ``fulltext_artifact_id`` as a bare lookup
    without first confirming the manifest's own artifact record is
    identity-consistent with that same article. Raises
    ``DeltaReviewOperatorError`` on any mismatch."""
    artifacts_by_id = {artifact["artifact_id"]: artifact for artifact in manifest.get("artifacts", [])}
    for row in article_index_rows:
        if row.get("fulltext_status") != _FULLTEXT_ACQUIRED_STATUS or not row.get("fulltext_artifact_id"):
            continue
        artifact_id = row["fulltext_artifact_id"]
        artifact = artifacts_by_id.get(artifact_id)
        if artifact is None:
            raise DeltaReviewOperatorError(
                f"article {row.get('pmid')!r} references unknown fulltext_artifact_id {artifact_id!r}"
            )
        pmcid = row.get("pmcid")
        source_id = artifact.get("source_id")
        if pmcid and isinstance(source_id, str) and source_id.startswith("pmcid:"):
            expected_source_id = f"pmcid:{pmcid}"
            if source_id != expected_source_id:
                raise DeltaReviewOperatorError(
                    f"article {row.get('pmid')!r} fulltext artifact {artifact_id!r} source_id "
                    f"{source_id!r} is inconsistent with the article's own pmcid identity "
                    f"{expected_source_id!r}"
                )
        if pmcid:
            relative_path = artifact.get("relative_path") or ""
            if pmcid not in relative_path:
                raise DeltaReviewOperatorError(
                    f"article {row.get('pmid')!r} fulltext artifact {artifact_id!r} relative_path "
                    f"{relative_path!r} is inconsistent with the article's own pmcid identity "
                    f"{pmcid!r}"
                )


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
    parser.add_argument("--atlas-expert-packet", type=Path, required=True, help="path to the pinned Atlas expert-review packet (Markdown; hash/byte-length verified, never parsed as JSON)")
    parser.add_argument("--atlas-expert-form", type=Path, required=True, help="path to the pinned Atlas expert-review form (hash/byte-length verified, never parsed as JSON)")
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

    # Enforce the configured acquisition manifest schema/bundle_id AFTER
    # the exact hash pin (validate_acquisition_manifest already
    # re-verified the manifest's own self-hash and every artifact's
    # bytes): a byte-identical manifest can still drift structurally
    # relative to what this config expects to be reading.
    expected_schema = acquisition_pin.get("schema")
    if expected_schema is not None and manifest.get("schema") != expected_schema:
        raise DeltaReviewOperatorError(
            f"acquisition manifest schema does not match the configured pin: expected "
            f"{expected_schema!r}, found {manifest.get('schema')!r}"
        )
    expected_bundle_id = acquisition_pin.get("bundle_id")
    if expected_bundle_id is not None and manifest.get("bundle_id") != expected_bundle_id:
        raise DeltaReviewOperatorError(
            f"acquisition manifest bundle_id does not match the configured pin: expected "
            f"{expected_bundle_id!r}, found {manifest.get('bundle_id')!r}"
        )

    baseline_bytes = verify_baseline_inputs(config, args=args)

    article_index_rows = read_article_index_rows(
        manifest, args.acquisition_bundle_root, acquisition_pin["article_index"]["relative_path"]
    )
    _validate_fulltext_artifact_identities(article_index_rows, manifest)

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


def _resolve_and_preflight_summary_target(config: dict[str, Any], repo_root: Path) -> Path:
    """Resolve ``config['committed_summary_path']`` against the CANONICAL
    (fully resolved) repository root and preflight it BEFORE any external
    bundle publication is attempted: it must resolve strictly inside
    ``repo_root`` (an absolute or ``..``-escaping configured path is
    rejected) and must not already exist (or be a symlink/reparse point).
    Raises ``DeltaReviewOperatorError`` on either violation -- an invalid
    or pre-existing summary target means NO external run is ever
    attempted, preserving create-only semantics."""
    repo_root_resolved = Path(repo_root).resolve()
    configured = config["committed_summary_path"]
    candidate = repo_root_resolved / configured
    resolved = candidate.resolve()
    try:
        resolved.relative_to(repo_root_resolved)
    except ValueError as exc:
        raise DeltaReviewOperatorError(
            f"configured committed_summary_path {configured!r} must resolve inside the canonical "
            f"repository root {repo_root_resolved}; refusing to publish anything externally "
            f"(resolved to {resolved})"
        ) from exc
    if resolved.is_symlink() or resolved.exists():
        raise DeltaReviewOperatorError(
            f"committed summary target {resolved} already exists or is a symlink/reparse point; "
            "the summary is create-only and this run is refused before any external publication"
        )
    return resolved


def run_publish(args: argparse.Namespace) -> int:
    config = load_config(args.config)

    # Preflight the (optional) committed-summary target FIRST -- before any
    # input verification/scanning or external publication is attempted --
    # so an invalid or pre-existing summary target never leaves a
    # partially-published external run behind.
    summary_target: Path | None = None
    if args.write_summary:
        summary_target = _resolve_and_preflight_summary_target(config, args.repo_root)

    prepared = _verify_inputs_and_scan(config, args)

    baseline_source_ids = derive_baseline_source_ids(prepared["baseline_bytes"]["rescuescreen_master_inventory"])
    proposition_vocabulary = derive_proposition_vocabulary(prepared["baseline_bytes"]["rescuescreen_master_inventory"])
    allowed_claim_ids = set(config["supervised_delta_review"]["baseline_relation"]["claims"])

    review_records = _read_review_records_jsonl(args.review_records)

    representative = representative_candidate_ids(prepared["candidate_spans"])
    valid_candidate_ids_by_source: dict[str, set[str]] = {}
    spans_by_candidate_id: dict[str, dict[str, Any]] = {}
    for span in prepared["candidate_spans"]:
        source_id = f"PMID:{span['article_identity']['pmid']}"
        valid_candidate_ids_by_source.setdefault(source_id, set()).add(span["candidate_id"])
        spans_by_candidate_id[span["candidate_id"]] = span
    for record in review_records:
        source_id = record.get("source_id")
        candidate_id = record.get("candidate_id")
        valid_ids = valid_candidate_ids_by_source.get(source_id, set())
        if candidate_id not in valid_ids:
            raise DeltaReviewOperatorError(
                f"review record for {source_id!r} references candidate_id {candidate_id!r}, which "
                f"is not one of that source's own candidate spans {sorted(valid_ids)!r}"
            )
        # Bind the record's own article_identity exactly to the selected
        # candidate span BEFORE any publication: a record whose
        # article_identity does not agree with the span/source it claims
        # to review must never reach the final bundle.
        selected_span = spans_by_candidate_id.get(candidate_id)
        if (
            selected_span is not None
            and "article_identity" in record
            and record["article_identity"] != selected_span["article_identity"]
        ):
            raise DeltaReviewOperatorError(
                f"review record for {source_id!r} article_identity {record['article_identity']!r} "
                "does not match the selected candidate span's own article_identity "
                f"{selected_span['article_identity']!r}"
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

    # title_or_abstract_candidate_sources / fulltext_body_candidate_sources
    # both count UNIQUE candidate SOURCES, never candidate SPAN records --
    # a source with both a matching title span and a matching abstract
    # span is still exactly one candidate source.
    title_or_abstract_sources = {
        f"PMID:{span['article_identity']['pmid']}"
        for span in prepared["candidate_spans"]
        if span["surface"] in (_TITLE_SURFACE, _ABSTRACT_SURFACE)
    }
    fulltext_body_sources = {
        f"PMID:{span['article_identity']['pmid']}"
        for span in prepared["candidate_spans"]
        if span["surface"] == _JATS_BODY_SURFACE
    }

    # canonical_alias_candidate_sources / conditional_legacy_only_candidate_sources:
    # derived PER UNIQUE SOURCE from its own spans' matched_aliases -- a
    # source counts as "canonical" if ANY of its spans matched a
    # canonical alias, and as "legacy-only" only when it matched a
    # conditional legacy alias (e.g. G1832A/1832G>A) on AT LEAST ONE span
    # but never a canonical alias anywhere. Every candidate source is
    # exactly one of these two (canonical_alias_candidate_sources +
    # conditional_legacy_only_candidate_sources == exact_alias_candidate_
    # sources), since a candidate source's disposition already requires
    # at least one canonical-or-conditional-legacy alias match.
    _canonical_alias_set = set(dr.CANONICAL_ALIASES)
    _legacy_alias_set = set(dr.CONDITIONAL_LEGACY_ALIASES)
    source_has_canonical: dict[str, bool] = {}
    source_has_legacy: dict[str, bool] = {}
    for span in prepared["candidate_spans"]:
        source_id = f"PMID:{span['article_identity']['pmid']}"
        matched = set(span.get("matched_aliases", []))
        if matched & _canonical_alias_set:
            source_has_canonical[source_id] = True
        if matched & _legacy_alias_set:
            source_has_legacy[source_id] = True
    canonical_alias_candidate_sources = {
        source_id for source_id in prepared["candidate_source_ids"] if source_has_canonical.get(source_id)
    }
    conditional_legacy_only_candidate_sources = {
        source_id
        for source_id in prepared["candidate_source_ids"]
        if source_has_legacy.get(source_id) and not source_has_canonical.get(source_id)
    }

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
            "title_or_abstract_candidate_sources": len(title_or_abstract_sources),
            "fulltext_body_candidate_sources": len(fulltext_body_sources),
            "canonical_alias_candidate_sources": len(canonical_alias_candidate_sources),
            "conditional_legacy_only_candidate_sources": len(conditional_legacy_only_candidate_sources),
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

    # Stage the committed-summary bytes BEFORE the external bundle is
    # published: if building/serializing the summary itself would fail,
    # that failure must happen before, not after, external publication --
    # a failure here can never leave a published external bundle without
    # a matching (attempted) summary write.
    summary_payload: bytes | None = None
    if summary_target is not None:
        summary = dr.build_committed_summary(manifest)
        summary_payload = (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode("utf-8")

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

    if summary_target is not None:
        try:
            summary_target.parent.mkdir(parents=True, exist_ok=True)
            with open(str(summary_target), "xb") as handle:
                handle.write(summary_payload)
        except OSError as exc:
            # Sanitized, single-line, typed failure -- never a raw
            # traceback: the external bundle was already published
            # successfully above, and only this separately opted-into
            # summary write failed.
            raise DeltaReviewOperatorError(
                f"failed to write committed summary (create-only) to {summary_target} after "
                f"external publication already succeeded ({type(exc).__name__})"
            ) from exc
        print(f"committed summary written: {summary_target}")

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
