"""R611Q literature acquisition-delta review: secure JATS block extraction,
deterministic alias matching, candidate-span/review-record validation, and
external create-only publication of a supervised, explicitly-unaccepted
delta-review addendum.

This module performs NO network I/O and never imports ``raptor.atlas``,
``raptor.rescuescreen``, ``raptor.scorer``, ``raptor.eval``,
``raptor.packet``, ``raptor.census`` or ``raptor.kb``. It reuses this
sibling package's (``raptor.external.r611q_literature.bundle``) hardened
symlink-safe, atomic, create-only directory publication primitive
(``raptor.external.tsc2_sources.bundle._publish_directory_no_replace``)
rather than re-implementing platform-specific atomic-rename handling.

Everything here is deterministic and pure: given the same acquisition
bundle bytes, the same frozen JATS XML text and the same alias
vocabulary, ``extract_jats_blocks``/``match_aliases`` always produce the
same blocks, locators and matched aliases. All fallible operations raise
the single ``DeltaReviewError`` exception (never a broad ``except`` that
masks a real failure as success, and never a bare ``Exception``): a
caller can always catch exactly one type for every contract violation
this module enforces.

Pipeline (see ``scripts/build_r611q_literature_delta_review.py`` for the
offline ``prepare``/``publish`` operator that drives this module over
real frozen inputs):

1. ``validate_acquisition_manifest`` re-verifies the acquisition bundle's
   own self-hash and every referenced artifact's bytes on disk (never
   trusting the manifest's recorded hashes without recomputing them).
2. ``extract_jats_blocks`` secure-parses one frozen JATS XML document
   (rejecting a DOCTYPE/ENTITY declaration, requiring ``article/body``,
   excluding ``ref-list``) into the smallest matching ``p``/``tr``/
   ``caption`` blocks, each carrying deterministic NFC/whitespace-
   collapsed text, a ``text-char:<start>:<end>`` locator into the
   deterministic joined body text, and section/table context (including
   transposed-table header/coordinate context).
3. ``match_aliases`` finds the canonical R611Q alias vocabulary
   (token-boundary, case-insensitive) plus the conditional legacy
   nucleotide-only aliases (accepted only alongside a canonical alias or
   a $TSC2$/tuberin context mention in the same block).
4. ``validate_article_dispositions`` requires every acquisition
   article-index row to receive exactly one disposition, and rejects any
   disposition outside the fixed three-value vocabulary (a source with
   no match is never labelled irrelevant).
5. ``validate_candidate_spans`` re-verifies every candidate span's
   article identity, source-artifact hash, locator/quote/hash
   reproduction, sorted/unique/non-empty matched aliases and exact
   candidate-span field set.
6. ``validate_review_records`` enforces the supervised-review contract:
   enum vocabularies, exactly-one-to-one candidate-source coverage,
   baseline source-identity collision rejection, proposition-vocabulary
   membership, the ``SECONDARY_REVIEW``/``ALLELE_BEARING_MODEL_CONTEXT``
   guard rules, and that every record leaves the existing proposed
   claims and Gate 8 state completely unchanged.
7. ``write_delta_bundle`` publishes the four final artifacts externally,
   create-only, symlink-safe, with the manifest written last.
8. ``build_committed_summary`` projects a strict aggregate-only summary
   from an already self-hash-validated manifest -- it never copies a
   PMID/PMCID/DOI/title/quote/locator/proposed-statement into the
   summary.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import unicodedata
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from raptor.external.tsc2_sources.bundle import _publish_directory_no_replace

MANIFEST_FILENAME = "bundle_manifest.json"

ARTICLE_INDEX_SCHEMA = "raptor.external.r611q_literature_article.v1"
CANDIDATE_SPAN_SCHEMA = "raptor.external.r611q_literature_delta_candidate_span.v1"
REVIEW_RECORD_SCHEMA = "raptor.external.r611q_literature_delta_review_record.v1"
DELTA_BUNDLE_MANIFEST_SCHEMA = "raptor.external.r611q_literature_delta_review_bundle.v1"
DELTA_PREPARATION_MANIFEST_SCHEMA = "raptor.external.r611q_literature_delta_review_preparation.v1"
COMMITTED_SUMMARY_SCHEMA = "raptor.external.r611q_literature_delta_review_committed_summary.v1"

#: The fixed R611Q canonical alias vocabulary (spec
#: ``deterministic_preselection.alias_classes.canonical``).
CANONICAL_ALIASES: tuple[str, ...] = (
    "rs28934872",
    "c.1832G>A",
    "NM_000548.5:c.1832G>A",
    "p.Arg611Gln",
    "NP_000539.2:p.Arg611Gln",
    "Arg611Gln",
    "p.R611Q",
    "R611Q",
)
#: Legacy nucleotide-only aliases: a candidate only in the presence of a
#: canonical alias or a $TSC2$/tuberin context mention in the same block
#: (spec ``deterministic_preselection.alias_classes.conditional_legacy``).
CONDITIONAL_LEGACY_ALIASES: tuple[str, ...] = ("1832G>A", "G1832A")

ARTICLE_INDEX_FIELDS = frozenset(
    {
        "schema",
        "pmid",
        "discovery_sources",
        "pubmed_status",
        "pmcid",
        "doi",
        "title",
        "publication_date",
        "publication_date_precision",
        "abstract",
        "europe_pmc_status",
        "is_open_access",
        "licence",
        "fulltext_status",
        "fulltext_artifact_id",
    }
)

CANDIDATE_SPAN_FIELDS = frozenset(
    {
        "schema",
        "candidate_id",
        "article_identity",
        "source_artifact_id",
        "source_artifact_sha256",
        "surface",
        "block_index",
        "block_tag",
        "context",
        "locator",
        "exact_quote",
        "exact_quote_sha256",
        "matched_aliases",
        "review_state",
    }
)

REVIEW_RECORD_FIELDS = frozenset(
    {
        "schema",
        "source_id",
        "article_identity",
        "candidate_id",
        "source_role",
        "primary_result_state",
        "baseline_relation",
        "baseline_claim_id",
        "delta_value",
        "proposition_ids",
        "context",
        "review_kind",
        "acceptance_state",
        "human_gate_8_effect",
        "claim_change",
        "gate_8_change",
    }
)

DISPOSITIONS = frozenset(
    {
        "EXACT_ALIAS_CANDIDATE",
        "NO_EXACT_ALIAS_IN_AVAILABLE_TEXT",
        "SOURCE_TEXT_UNAVAILABLE",
    }
)
SOURCE_ROLES = frozenset(
    {
        "DIRECT_ALLELE_EXPERIMENT",
        "ALLELE_BEARING_MODEL_CONTEXT",
        "CLINICAL_CASE_IDENTITY",
        "SECONDARY_REVIEW",
        "NOT_RELEVANT",
    }
)
PRIMARY_RESULT_STATES = frozenset(
    {
        "PRIMARY_R611Q_RESULT",
        "PRIMARY_VARIANT_BEARING_MODEL_RESULT",
        "CASE_OR_COHORT_OBSERVATION",
        "SECONDARY_SYNTHESIS_ONLY",
        "NO_R611Q_RESULT",
    }
)
BASELINE_RELATIONS = frozenset(
    {"SUPPORTS", "NARROWS", "CONTRADICTS", "ORTHOGONAL", "NO_DIRECT_RELATION"}
)
DELTA_VALUES = frozenset(
    {
        "NEW_PRIMARY_OBSERVATION",
        "NEW_ASSAY_OR_MODEL_CONTEXT",
        "NEW_CLINICAL_OCCURRENCE",
        "SECONDARY_ONLY",
        "NO_MATERIAL_DELTA",
    }
)
REQUIRED_CONTEXT_FIELDS: tuple[str, ...] = (
    "r611q_role",
    "model_system",
    "perturbation",
    "comparator",
    "readout",
    "directness",
    "assay_lineage",
    "independence",
    "limitations",
)

_HEX64_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_LOCATOR_PATTERN = re.compile(r"^text-char:(\d+):(\d+)$")


class DeltaReviewError(ValueError):
    """Raised for every contract violation this module enforces: manifest
    self-hash/artifact mismatch, insecure JATS XML, malformed alias/
    disposition/candidate-span/review-record shapes, a baseline source-
    identity collision, a claim/Gate-8 mutation attempt, or an output-path
    boundary violation (inside-repository, non-create-only, symlink/
    reparse-point or path-escape). This is the ONLY exception type this
    module raises; callers never need to catch multiple exception classes
    from this module."""


# ---------------------------------------------------------------------------
# Canonical hashing helpers
# ---------------------------------------------------------------------------


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def compute_manifest_content_hash(manifest: dict[str, Any]) -> str:
    """SHA-256 of ``manifest``'s UTF-8 canonical JSON (sorted object keys,
    ``(",", ":")`` separators, array order preserved), excluding ONLY the
    top-level ``content_hash`` key itself. Key-order invariant, byte-
    sensitive to any other content change."""
    if not isinstance(manifest, dict):
        raise DeltaReviewError(f"manifest must be a mapping: {type(manifest).__name__}")
    basis = {key: value for key, value in manifest.items() if key != "content_hash"}
    return _sha256_text(_canonical_json(basis))


def _safe_join(base: Path, relative_path: str) -> Path:
    """Join ``relative_path`` onto ``base`` and raise ``DeltaReviewError``
    if the resolved result escapes ``base`` (path traversal, absolute
    override, etc.)."""
    candidate = (base / relative_path).resolve()
    base_resolved = base.resolve()
    try:
        candidate.relative_to(base_resolved)
    except ValueError as exc:
        raise DeltaReviewError(
            f"relative_path {relative_path!r} escapes the expected root directory {base}"
        ) from exc
    return candidate


# ---------------------------------------------------------------------------
# Acquisition manifest re-verification
# ---------------------------------------------------------------------------


def validate_acquisition_manifest(
    *,
    manifest_path: Path,
    bundle_root: Path,
    expected_manifest_content_hash: str,
    expected_manifest_file_sha256: str,
    expected_manifest_byte_length: int,
    expected_article_index: dict[str, Any],
) -> dict[str, Any]:
    """Re-verify the acquisition bundle's manifest FILE bytes (byte length
    and sha256) against the pinned config values, re-verify the manifest's
    own canonical ``content_hash`` against its recomputed value AND the
    pinned expected value, then re-verify every artifact the manifest
    references (byte length and sha256) against the bytes actually on
    disk under ``bundle_root`` -- including a dedicated re-check of the
    pinned article-index artifact (byte length, sha256 and JSONL row
    count). Returns ``{"manifest": <parsed manifest>, "article_index_row_
    count": <int>}``. Raises ``DeltaReviewError`` on ANY mismatch; never
    trusts a manifest-recorded hash without recomputing it from real
    bytes on disk."""
    manifest_path = Path(manifest_path)
    bundle_root = Path(bundle_root)

    if not manifest_path.is_file():
        raise DeltaReviewError(f"acquisition manifest file not found: {manifest_path}")

    manifest_bytes = manifest_path.read_bytes()
    observed_byte_length = len(manifest_bytes)
    if observed_byte_length != expected_manifest_byte_length:
        raise DeltaReviewError(
            f"acquisition manifest byte_length mismatch: expected "
            f"{expected_manifest_byte_length!r}, observed {observed_byte_length!r}"
        )
    observed_file_sha256 = _sha256_bytes(manifest_bytes)
    if observed_file_sha256.lower() != str(expected_manifest_file_sha256).lower():
        raise DeltaReviewError(
            f"acquisition manifest sha256 mismatch: expected "
            f"{expected_manifest_file_sha256!r}, observed {observed_file_sha256!r}"
        )

    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeltaReviewError(f"acquisition manifest is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise DeltaReviewError("acquisition manifest must decode to a JSON object")

    recomputed_content_hash = compute_manifest_content_hash(manifest)
    stored_content_hash = manifest.get("content_hash")
    if recomputed_content_hash != stored_content_hash:
        raise DeltaReviewError(
            f"acquisition manifest content_hash self-mismatch: recorded "
            f"{stored_content_hash!r}, recomputed {recomputed_content_hash!r}"
        )
    if stored_content_hash != expected_manifest_content_hash:
        raise DeltaReviewError(
            f"acquisition manifest content_hash does not match the pinned expected value: "
            f"expected {expected_manifest_content_hash!r}, found {stored_content_hash!r}"
        )

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise DeltaReviewError("acquisition manifest 'artifacts' must be a list")

    article_index_relative_path = expected_article_index["relative_path"]
    article_index_row_count: int | None = None

    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise DeltaReviewError(f"acquisition manifest artifact record is not a mapping: {artifact!r}")
        relative_path = artifact.get("relative_path")
        recorded_sha256 = artifact.get("sha256")
        recorded_byte_length = artifact.get("byte_length")
        if not isinstance(relative_path, str) or not relative_path:
            raise DeltaReviewError(f"acquisition manifest artifact record has no relative_path: {artifact!r}")
        artifact_path = _safe_join(bundle_root, relative_path)
        if not artifact_path.is_file():
            raise DeltaReviewError(f"acquisition artifact file missing on disk: {relative_path!r}")
        artifact_bytes = artifact_path.read_bytes()
        if len(artifact_bytes) != recorded_byte_length:
            raise DeltaReviewError(
                f"acquisition artifact {relative_path!r} byte_length mismatch: manifest records "
                f"{recorded_byte_length!r}, observed {len(artifact_bytes)!r}"
            )
        observed_sha256 = _sha256_bytes(artifact_bytes)
        if observed_sha256.lower() != str(recorded_sha256).lower():
            raise DeltaReviewError(
                f"acquisition artifact {relative_path!r} sha256 mismatch: manifest records "
                f"{recorded_sha256!r}, observed {observed_sha256!r}"
            )

        if relative_path == article_index_relative_path:
            row_count = sum(1 for line in artifact_bytes.decode("utf-8").splitlines() if line.strip())
            article_index_row_count = row_count
            if len(artifact_bytes) != expected_article_index["byte_length"]:
                raise DeltaReviewError(
                    f"acquisition article index byte_length does not match the pinned expected "
                    f"value: expected {expected_article_index['byte_length']!r}, observed "
                    f"{len(artifact_bytes)!r}"
                )
            if observed_sha256.lower() != str(expected_article_index["sha256"]).lower():
                raise DeltaReviewError(
                    f"acquisition article index sha256 does not match the pinned expected "
                    f"value: expected {expected_article_index['sha256']!r}, observed "
                    f"{observed_sha256!r}"
                )
            if row_count != expected_article_index["rows"]:
                raise DeltaReviewError(
                    f"acquisition article index row count does not match the pinned expected "
                    f"value: expected {expected_article_index['rows']!r}, observed {row_count!r}"
                )

    if article_index_row_count is None:
        raise DeltaReviewError(
            f"acquisition manifest does not reference the expected article index artifact "
            f"{article_index_relative_path!r}"
        )

    return {"manifest": manifest, "article_index_row_count": article_index_row_count}


# ---------------------------------------------------------------------------
# Secure JATS block extraction
# ---------------------------------------------------------------------------


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    return re.sub(r"\s+", " ", normalized).strip()


def _node_text(node: ET.Element) -> str:
    return _normalize_text(" ".join(part for part in node.itertext()))


def _is_descendant(
    node: ET.Element, ancestor: ET.Element, parent_by_child: dict[ET.Element, ET.Element]
) -> bool:
    cursor = node
    while cursor in parent_by_child:
        cursor = parent_by_child[cursor]
        if cursor is ancestor:
            return True
    return False


def _ancestor_chain(node: ET.Element, parent_by_child: dict[ET.Element, ET.Element]) -> list[ET.Element]:
    chain = [node]
    cursor = node
    while cursor in parent_by_child:
        cursor = parent_by_child[cursor]
        chain.append(cursor)
    return chain


def _nearest_ancestor_by_tag(
    node: ET.Element, *, parent_by_child: dict[ET.Element, ET.Element], tag: str
) -> ET.Element | None:
    cursor: ET.Element | None = node
    while cursor is not None:
        if _local_name(cursor.tag) == tag:
            return cursor
        cursor = parent_by_child.get(cursor)
    return None


def _section_title_path(node: ET.Element, parent_by_child: dict[ET.Element, ET.Element]) -> list[str]:
    titles: list[str] = []
    for ancestor in reversed(_ancestor_chain(node, parent_by_child)):
        if _local_name(ancestor.tag) != "sec":
            continue
        title_node = next((child for child in list(ancestor) if _local_name(child.tag) == "title"), None)
        if title_node is None:
            continue
        title_text = _node_text(title_node)
        if title_text:
            titles.append(title_text)
    return titles


def _table_headers_for_row(row: ET.Element, parent_by_child: dict[ET.Element, ET.Element]) -> list[str]:
    table_node = _nearest_ancestor_by_tag(row, parent_by_child=parent_by_child, tag="table")
    if table_node is None:
        return []
    for tr in table_node.iter():
        if _local_name(tr.tag) != "tr":
            continue
        headers = [
            _node_text(cell) for cell in list(tr) if _local_name(cell.tag) == "th" and _node_text(cell)
        ]
        if headers:
            return headers
    return []


def _table_wrap_label_and_caption(
    node: ET.Element, parent_by_child: dict[ET.Element, ET.Element]
) -> tuple[str | None, str | None]:
    wrap = _nearest_ancestor_by_tag(node, parent_by_child=parent_by_child, tag="table-wrap")
    label_text = None
    caption_text = None
    if wrap is not None:
        label_node = next((child for child in list(wrap) if _local_name(child.tag) == "label"), None)
        if label_node is not None:
            label_text = _node_text(label_node) or None
        caption_node = next((child for child in list(wrap) if _local_name(child.tag) == "caption"), None)
        if caption_node is not None:
            caption_text = _node_text(caption_node) or None
    return label_text, caption_text


def _row_context_text(row: ET.Element, parent_by_child: dict[ET.Element, ET.Element]) -> str:
    """The additional table-level text (label, caption, column headers) a
    table row's cells are read alongside -- used ONLY to decide whether a
    conditional legacy alias is in-context (see ``_block_match_aliases``);
    it never becomes part of a reported ``matched_aliases``/``exact_quote``
    value, which always come from the block's own text alone."""
    label_text, caption_text = _table_wrap_label_and_caption(row, parent_by_child)
    headers = _table_headers_for_row(row, parent_by_child)
    return " ".join(part for part in ([label_text, caption_text] + headers) if part)


def _row_match_coordinates(
    row: ET.Element, parent_by_child: dict[ET.Element, ET.Element], context_text: str
) -> list[dict[str, int]]:
    table_node = _nearest_ancestor_by_tag(row, parent_by_child=parent_by_child, tag="table")
    row_number = 1
    if table_node is not None:
        ordered_rows = [node for node in table_node.iter() if _local_name(node.tag) == "tr"]
        for idx, candidate in enumerate(ordered_rows, start=1):
            if candidate is row:
                row_number = idx
                break

    coordinates: list[dict[str, int]] = []
    col_idx = 0
    for child in list(row):
        child_tag = _local_name(child.tag)
        if child_tag not in {"td", "th"}:
            continue
        col_idx += 1
        cell_text = _node_text(child)
        if not cell_text:
            continue
        if _block_match_aliases(cell_text, context_text):
            coordinates.append({"row": row_number, "column": col_idx})
    return coordinates


def _context_for_block(node: ET.Element, tag: str, parent_by_child: dict[ET.Element, ET.Element]) -> dict[str, Any]:
    section_path = _section_title_path(node, parent_by_child)
    context: dict[str, Any] = {"section_title_path": section_path}

    if tag == "tr":
        label_text, caption_text = _table_wrap_label_and_caption(node, parent_by_child)
        context_text = _row_context_text(node, parent_by_child)
        context.update(
            {
                "table_label": label_text,
                "table_caption": caption_text,
                "column_headers": _table_headers_for_row(node, parent_by_child),
                "matching_cell_coordinates": _row_match_coordinates(node, parent_by_child, context_text),
            }
        )
    elif tag == "caption":
        label_text, _caption_text = _table_wrap_label_and_caption(node, parent_by_child)
        if label_text is not None:
            context["table_label"] = label_text

    return context


def _legacy_context_text_for_block(tag: str, node: ET.Element, parent_by_child: dict[ET.Element, ET.Element]) -> str:
    """The additional structural text (beyond the block's own text) that
    counts towards ``$TSC2$``/tuberin/canonical-alias context eligibility
    for a conditional legacy alias (spec's ``conditional_rule``): a table
    row is read alongside its table's label/caption/column headers, and a
    caption alongside its table's label. A plain paragraph has no such
    additional structural context -- only its own text is ever
    considered."""
    if tag == "tr":
        return _row_context_text(node, parent_by_child)
    if tag == "caption":
        label_text, _caption_text = _table_wrap_label_and_caption(node, parent_by_child)
        return label_text or ""
    return ""


def extract_jats_blocks(*, xml_text: str) -> dict[str, Any]:
    """Secure-parse ``xml_text`` (rejecting a DOCTYPE/ENTITY declaration
    BEFORE ever invoking the XML parser) and extract the smallest matching
    ``p``/``tr``/``caption`` blocks under ``article/body`` (excluding the
    ``ref-list`` subtree entirely). Each block gets deterministic NFC/
    whitespace-collapsed text, a ``text-char:<start>:<end>`` locator into
    the LF-joined deterministic body text, its matched aliases (see
    ``match_aliases``) and section/table context (a transposed table row
    preserves its label/caption/column headers and matching cell
    coordinates). Returns ``{"joined_text": str, "blocks": [...]}``.
    Raises ``DeltaReviewError`` if a DOCTYPE/ENTITY declaration is present,
    the document fails to parse, the root element is not ``article``, or
    ``article/body`` is absent."""
    if not isinstance(xml_text, str):
        raise DeltaReviewError("xml_text must be a string")
    lowered = xml_text.lower()
    if "<!doctype" in lowered:
        raise DeltaReviewError("JATS XML DOCTYPE declaration is forbidden for secure parsing")
    if "<!entity" in lowered:
        raise DeltaReviewError("JATS XML ENTITY declaration is forbidden for secure parsing")

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise DeltaReviewError(f"JATS XML failed to parse: {exc}") from exc

    if _local_name(root.tag) != "article":
        raise DeltaReviewError("JATS XML root element must be 'article'")
    body = root.find("./body")
    if body is None:
        raise DeltaReviewError("JATS XML article/body is required")

    parent_by_child: dict[ET.Element, ET.Element] = {}
    for parent in body.iter():
        for child in parent:
            parent_by_child[child] = parent

    block_tags = {"p", "tr", "caption"}
    blocks: list[tuple[ET.Element, str, str, list[str], dict[str, Any]]] = []

    def walk(node: ET.Element, excluded: bool = False) -> None:
        tag = _local_name(node.tag)
        next_excluded = excluded or tag == "ref-list"
        if next_excluded:
            return
        if tag in block_tags:
            text = _node_text(node)
            if text:
                context_text = _legacy_context_text_for_block(tag, node, parent_by_child)
                matches = _block_match_aliases(text, context_text)
                context = _context_for_block(node, tag, parent_by_child)
                blocks.append((node, tag, text, matches, context))
        for child in list(node):
            walk(child, excluded=next_excluded)

    walk(body)

    selected: list[tuple[str, str, list[str], dict[str, Any]]] = []
    for node, tag, text, matches, context in blocks:
        if not matches:
            continue
        has_matching_descendant = any(
            other_matches and other_text == text and _is_descendant(other_node, node, parent_by_child)
            for other_node, _other_tag, other_text, other_matches, _other_context in blocks
            if other_node is not node
        )
        if has_matching_descendant:
            continue
        selected.append((tag, text, matches, context))

    joined_text_parts: list[str] = []
    records: list[dict[str, Any]] = []
    cursor = 0
    for index, (tag, text, matches, context) in enumerate(selected):
        joined_text_parts.append(text)
        start = cursor
        end = cursor + len(text)
        records.append(
            {
                "block_index": index,
                "block_tag": tag,
                "context": context,
                "locator": f"text-char:{start}:{end}",
                "text": text,
                "matched_aliases": matches,
            }
        )
        cursor = end + 1

    return {"joined_text": "\n".join(joined_text_parts), "blocks": records}


# ---------------------------------------------------------------------------
# Alias matching
# ---------------------------------------------------------------------------


def _compile_alias_pattern(alias: str) -> re.Pattern[str]:
    escaped = re.escape(alias)
    escaped = escaped.replace(">", r"\s*>\s*")
    return re.compile(rf"(?<![0-9A-Za-z_]){escaped}(?![0-9A-Za-z_])", re.IGNORECASE)


_CANONICAL_PATTERNS = {alias: _compile_alias_pattern(alias) for alias in CANONICAL_ALIASES}
_LEGACY_PATTERNS = {alias: _compile_alias_pattern(alias) for alias in CONDITIONAL_LEGACY_ALIASES}
_CONTEXT_PATTERN = re.compile(r"(?<![0-9A-Za-z_])(tsc2|tuberin)(?![0-9A-Za-z_])", re.IGNORECASE)


def match_aliases(
    text: str,
    *,
    canonical_aliases: tuple[str, ...] = CANONICAL_ALIASES,
    conditional_legacy_aliases: tuple[str, ...] = CONDITIONAL_LEGACY_ALIASES,
) -> list[str]:
    """Return the sorted, deduplicated (case-folded) list of aliases
    matched in ``text``: every canonical alias found via case-insensitive,
    token-boundary matching (an HGVS ``>`` arrow may have surrounding
    whitespace), plus every conditional legacy nucleotide-only alias
    found -- but ONLY when at least one canonical alias OR a $TSC2$/
    tuberin context mention is also present in ``text``. Defaults to the
    fixed R611Q vocabulary; a caller may override both vocabularies for a
    different variant/config."""
    if not isinstance(text, str):
        raise DeltaReviewError("text must be a string")

    canonical_patterns = (
        _CANONICAL_PATTERNS
        if canonical_aliases == CANONICAL_ALIASES
        else {alias: _compile_alias_pattern(alias) for alias in canonical_aliases}
    )
    legacy_patterns = (
        _LEGACY_PATTERNS
        if conditional_legacy_aliases == CONDITIONAL_LEGACY_ALIASES
        else {alias: _compile_alias_pattern(alias) for alias in conditional_legacy_aliases}
    )

    canonical_hits = [alias for alias, pattern in canonical_patterns.items() if pattern.search(text)]
    context_ok = bool(canonical_hits) or _CONTEXT_PATTERN.search(text) is not None
    legacy_hits: list[str] = []
    if context_ok:
        legacy_hits = [alias for alias, pattern in legacy_patterns.items() if pattern.search(text)]
    return sorted(set(canonical_hits + legacy_hits), key=lambda v: (v.casefold(), v))


def _block_match_aliases(text: str, context_text: str) -> list[str]:
    """Same alias-matching contract as ``match_aliases``, except a
    conditional legacy alias present in ``text`` is ALSO accepted when a
    $TSC2$/tuberin mention or a canonical alias is found in
    ``context_text`` rather than in ``text`` itself -- e.g. a table row
    whose own cells never say ``TSC2``/``tuberin`` but whose enclosing
    table's label/caption/column headers do (see
    ``_legacy_context_text_for_block``). ``matched_aliases`` is still
    always derived from ``text`` alone: a context-only mention is never
    reported as a match on the block that did not itself contain it."""
    canonical_hits = [alias for alias, pattern in _CANONICAL_PATTERNS.items() if pattern.search(text)]
    context_ok = bool(canonical_hits) or _CONTEXT_PATTERN.search(text) is not None
    if not context_ok and context_text:
        context_ok = _CONTEXT_PATTERN.search(context_text) is not None or any(
            pattern.search(context_text) for pattern in _CANONICAL_PATTERNS.values()
        )
    legacy_hits: list[str] = []
    if context_ok:
        legacy_hits = [alias for alias, pattern in _LEGACY_PATTERNS.items() if pattern.search(text)]
    return sorted(set(canonical_hits + legacy_hits), key=lambda v: (v.casefold(), v))


def _candidate_id(article_identity: dict[str, Any], surface: str, block_index: int) -> str:
    """Deterministic 24-hex-character candidate id derived from exactly
    (article identity, surface, block index) -- never from the matched
    aliases or quote text, so re-running preselection over the same
    frozen input always reproduces the same id."""
    basis = {"article_identity": article_identity, "surface": surface, "block_index": block_index}
    return _sha256_text(_canonical_json(basis))[:24]


# ---------------------------------------------------------------------------
# Article dispositions
# ---------------------------------------------------------------------------


def _row_article_identity(row: dict[str, Any]) -> dict[str, Any]:
    return {"pmid": row.get("pmid"), "pmcid": row.get("pmcid"), "doi": row.get("doi")}


def validate_article_dispositions(
    *, article_index_rows: list[dict[str, Any]], dispositions: list[dict[str, Any]]
) -> None:
    """Require ``dispositions`` to cover every ``article_index_rows`` entry
    EXACTLY once (by derived ``{pmid, pmcid, doi}`` article identity --
    never missing, never duplicated, never an extra entry) and every
    ``disposition`` value to be one of the fixed three-value vocabulary
    (``EXACT_ALIAS_CANDIDATE``/``NO_EXACT_ALIAS_IN_AVAILABLE_TEXT``/
    ``SOURCE_TEXT_UNAVAILABLE`` -- a source with no exact-alias match is
    lexical non-recall, never labelled irrelevant). Raises
    ``DeltaReviewError`` on any violation."""
    if not isinstance(article_index_rows, list) or not isinstance(dispositions, list):
        raise DeltaReviewError("article_index_rows and dispositions must both be lists")

    expected_keys = [_canonical_json(_row_article_identity(row)) for row in article_index_rows]
    expected_counter: dict[str, int] = {}
    for key in expected_keys:
        expected_counter[key] = expected_counter.get(key, 0) + 1

    observed_counter: dict[str, int] = {}
    for entry in dispositions:
        if not isinstance(entry, dict) or "article_identity" not in entry or "disposition" not in entry:
            raise DeltaReviewError(f"disposition record missing required fields: {entry!r}")
        disposition = entry["disposition"]
        if disposition not in DISPOSITIONS:
            raise DeltaReviewError(
                f"disposition {disposition!r} is not one of the allowed dispositions "
                f"{sorted(DISPOSITIONS)!r}; a source with no exact-alias match in available "
                "text is never labelled irrelevant"
            )
        key = _canonical_json(entry["article_identity"])
        observed_counter[key] = observed_counter.get(key, 0) + 1

    if observed_counter != expected_counter:
        missing = {
            k: expected_counter[k] - observed_counter.get(k, 0)
            for k in expected_counter
            if expected_counter[k] > observed_counter.get(k, 0)
        }
        extra = {
            k: observed_counter[k] - expected_counter.get(k, 0)
            for k in observed_counter
            if observed_counter[k] > expected_counter.get(k, 0)
        }
        raise DeltaReviewError(
            "article dispositions do not cover exactly one disposition per article-index row: "
            f"missing={missing!r} extra={extra!r}"
        )


# ---------------------------------------------------------------------------
# Candidate spans
# ---------------------------------------------------------------------------


def validate_candidate_spans(
    *,
    candidate_spans: list[dict[str, Any]],
    article_index_rows: list[dict[str, Any]],
    source_artifact_hashes: dict[str, str],
    joined_surface_text_by_artifact: dict[str, str],
) -> None:
    """Re-verify every candidate span: exact field set, agreement with the
    acquisition article index's identity, agreement of
    ``source_artifact_sha256`` with the acquisition manifest, a sorted/
    unique/non-empty ``matched_aliases`` list, exact reproduction of
    ``exact_quote`` from ``locator`` over the deterministic joined surface
    text, a matching ``exact_quote_sha256``, ``review_state`` exactly
    ``PROPOSED_UNACCEPTED``, and a deterministic ``candidate_id`` derived
    from exactly (article identity, surface, block index) with no
    duplicates. Raises ``DeltaReviewError`` on any violation."""
    if not isinstance(candidate_spans, list):
        raise DeltaReviewError("candidate_spans must be a list")

    known_identities = {_canonical_json(_row_article_identity(row)) for row in article_index_rows}
    seen_candidate_ids: set[str] = set()

    for span in candidate_spans:
        if not isinstance(span, dict) or set(span) != CANDIDATE_SPAN_FIELDS:
            missing = CANDIDATE_SPAN_FIELDS - set(span) if isinstance(span, dict) else CANDIDATE_SPAN_FIELDS
            extra = set(span) - CANDIDATE_SPAN_FIELDS if isinstance(span, dict) else set()
            raise DeltaReviewError(
                "candidate span record does not have the exact required fields (context is a "
                f"required, deterministic field): missing={sorted(missing)!r} extra={sorted(extra)!r}"
            )
        if span["schema"] != CANDIDATE_SPAN_SCHEMA:
            raise DeltaReviewError(f"candidate span schema mismatch: {span['schema']!r}")

        identity_key = _canonical_json(span["article_identity"])
        if identity_key not in known_identities:
            raise DeltaReviewError(
                f"candidate span article_identity does not agree exactly with the acquisition "
                f"article index: {span['article_identity']!r}"
            )

        source_artifact_id = span["source_artifact_id"]
        expected_hash = source_artifact_hashes.get(source_artifact_id)
        if expected_hash is None:
            raise DeltaReviewError(
                f"candidate span references unknown source_artifact_id {source_artifact_id!r}"
            )
        if str(span["source_artifact_sha256"]).lower() != str(expected_hash).lower():
            raise DeltaReviewError(
                f"candidate span source_artifact_sha256 does not agree with the acquisition "
                f"manifest for {source_artifact_id!r}: expected {expected_hash!r}, found "
                f"{span['source_artifact_sha256']!r}"
            )

        matched_aliases = span["matched_aliases"]
        if (
            not isinstance(matched_aliases, list)
            or not matched_aliases
            or len(matched_aliases) != len(set(matched_aliases))
            or matched_aliases != sorted(matched_aliases, key=lambda v: (v.casefold(), v))
        ):
            raise DeltaReviewError(
                f"candidate span matched_aliases must be a sorted, unique, non-empty list: "
                f"{matched_aliases!r}"
            )

        joined_text = joined_surface_text_by_artifact.get(source_artifact_id)
        if joined_text is None:
            raise DeltaReviewError(
                f"no deterministic joined surface text supplied for source_artifact_id "
                f"{source_artifact_id!r}"
            )
        locator_match = _LOCATOR_PATTERN.match(str(span["locator"]))
        if locator_match is None:
            raise DeltaReviewError(f"candidate span locator has an invalid shape: {span['locator']!r}")
        start, end = int(locator_match.group(1)), int(locator_match.group(2))
        if not (0 <= start <= end <= len(joined_text)):
            raise DeltaReviewError(f"candidate span locator is out of bounds: {span['locator']!r}")
        if joined_text[start:end] != span["exact_quote"]:
            raise DeltaReviewError(
                "candidate span locator does not reproduce exact_quote from the deterministic "
                f"extracted surface: locator={span['locator']!r}"
            )

        expected_quote_hash = _sha256_text(span["exact_quote"])
        if span["exact_quote_sha256"] != expected_quote_hash:
            raise DeltaReviewError(
                f"candidate span exact_quote_sha256 does not match exact_quote: expected "
                f"{expected_quote_hash!r}, found {span['exact_quote_sha256']!r}"
            )

        if span["review_state"] != "PROPOSED_UNACCEPTED":
            raise DeltaReviewError(
                f"candidate span review_state must be exactly PROPOSED_UNACCEPTED: "
                f"{span['review_state']!r}"
            )

        if not isinstance(span["candidate_id"], str) or not span["candidate_id"]:
            raise DeltaReviewError(f"candidate span candidate_id must be a non-empty string: {span['candidate_id']!r}")
        expected_candidate_id = _candidate_id(span["article_identity"], span["surface"], span["block_index"])
        if span["candidate_id"] != expected_candidate_id:
            raise DeltaReviewError(
                "candidate span candidate_id is not deterministic from article_identity/"
                f"surface/block_index: expected {expected_candidate_id!r}, found "
                f"{span['candidate_id']!r}"
            )
        if span["candidate_id"] in seen_candidate_ids:
            raise DeltaReviewError(f"duplicate candidate_id in candidate spans: {span['candidate_id']!r}")
        seen_candidate_ids.add(span["candidate_id"])


# ---------------------------------------------------------------------------
# Review records
# ---------------------------------------------------------------------------


def validate_review_records(
    *,
    review_records: list[dict[str, Any]],
    candidate_source_ids: set[str],
    baseline_source_ids: set[str],
    proposition_vocabulary: set[str],
    allowed_claim_ids: set[str],
) -> None:
    """Enforce the supervised-review contract over ``review_records``:
    exact field set/schema, enum vocabularies for ``source_role``/
    ``primary_result_state``/``baseline_relation``/``delta_value``,
    ``baseline_claim_id`` membership in ``allowed_claim_ids`` (or
    ``None``), ``proposition_ids`` membership in
    ``proposition_vocabulary``, the exact required ``context`` field set,
    that a ``SECONDARY_REVIEW`` source role never ``SUPPORTS``/
    ``CONTRADICTS`` a proposition, that an
    ``ALLELE_BEARING_MODEL_CONTEXT`` source role is never promoted to a
    direct ``PRIMARY_R611Q_RESULT``, that ``review_kind``/
    ``acceptance_state``/``human_gate_8_effect`` are fixed to the
    required model-assisted-unaccepted state, that ``claim_change``/
    ``gate_8_change`` are always ``NONE``, that no record's ``source_id``
    collides with ``baseline_source_ids``, and that the record set is
    exactly one-to-one with ``candidate_source_ids``. Raises
    ``DeltaReviewError`` on any violation."""
    if not isinstance(review_records, list):
        raise DeltaReviewError("review_records must be a list")

    observed_source_ids: set[str] = set()
    for record in review_records:
        if not isinstance(record, dict) or set(record) != REVIEW_RECORD_FIELDS:
            missing = REVIEW_RECORD_FIELDS - set(record) if isinstance(record, dict) else REVIEW_RECORD_FIELDS
            extra = set(record) - REVIEW_RECORD_FIELDS if isinstance(record, dict) else set()
            raise DeltaReviewError(
                f"review record does not have the exact required fields: missing="
                f"{sorted(missing)!r} extra={sorted(extra)!r}"
            )
        if record["schema"] != REVIEW_RECORD_SCHEMA:
            raise DeltaReviewError(f"review record schema mismatch: {record['schema']!r}")

        source_id = record["source_id"]
        if source_id in baseline_source_ids:
            raise DeltaReviewError(
                f"review source identity collision with the pinned baseline inventory: "
                f"{source_id!r} already exists in the RescueScreen baseline"
            )

        if record["source_role"] not in SOURCE_ROLES:
            raise DeltaReviewError(f"review record source_role is not a valid enum value: {record['source_role']!r}")
        if record["primary_result_state"] not in PRIMARY_RESULT_STATES:
            raise DeltaReviewError(
                f"review record primary_result_state is not a valid enum value: "
                f"{record['primary_result_state']!r}"
            )
        if record["baseline_relation"] not in BASELINE_RELATIONS:
            raise DeltaReviewError(
                f"review record baseline_relation is not a valid enum value: "
                f"{record['baseline_relation']!r}"
            )
        if record["delta_value"] not in DELTA_VALUES:
            raise DeltaReviewError(f"review record delta_value is not a valid enum value: {record['delta_value']!r}")

        baseline_claim_id = record["baseline_claim_id"]
        if baseline_claim_id is not None and baseline_claim_id not in allowed_claim_ids:
            raise DeltaReviewError(
                f"review record baseline_claim_id is not one of the allowed baseline claim ids "
                f"{sorted(allowed_claim_ids)!r}: {baseline_claim_id!r}"
            )

        proposition_ids = record["proposition_ids"]
        if not isinstance(proposition_ids, list):
            raise DeltaReviewError("review record proposition_ids must be a list")
        for proposition_id in proposition_ids:
            if proposition_id not in proposition_vocabulary:
                raise DeltaReviewError(
                    f"review record proposition_id {proposition_id!r} is not in the pinned "
                    "RescueScreen proposition vocabulary"
                )

        context = record["context"]
        if not isinstance(context, dict) or set(context) != set(REQUIRED_CONTEXT_FIELDS):
            observed = sorted(context) if isinstance(context, dict) else context
            raise DeltaReviewError(
                "review record context does not have the exact required context fields "
                f"{sorted(REQUIRED_CONTEXT_FIELDS)!r}: {observed!r}"
            )

        if record["source_role"] == "SECONDARY_REVIEW" and record["baseline_relation"] in ("SUPPORTS", "CONTRADICTS"):
            raise DeltaReviewError(
                "a SECONDARY_REVIEW source role cannot support or contradict a proposition: "
                f"baseline_relation={record['baseline_relation']!r}"
            )
        if (
            record["source_role"] == "ALLELE_BEARING_MODEL_CONTEXT"
            and record["primary_result_state"] == "PRIMARY_R611Q_RESULT"
        ):
            raise DeltaReviewError(
                "an ALLELE_BEARING_MODEL_CONTEXT source role measures only indirect, model-"
                "context results and cannot be promoted into a direct PRIMARY_R611Q_RESULT "
                "allele-mechanism statement"
            )

        if record["review_kind"] != "MODEL_ASSISTED_SOURCE_TRIAGE":
            raise DeltaReviewError(
                "review record review_kind must be exactly MODEL_ASSISTED_SOURCE_TRIAGE "
                f"(model-assisted triage is never treated as qualified human review): "
                f"{record['review_kind']!r}"
            )
        if record["acceptance_state"] != "PROPOSED_UNACCEPTED":
            raise DeltaReviewError(
                f"review record acceptance_state must be exactly PROPOSED_UNACCEPTED: "
                f"{record['acceptance_state']!r}"
            )
        if record["human_gate_8_effect"] != "NONE":
            raise DeltaReviewError(
                f"review record human_gate_8_effect must be exactly NONE: "
                f"{record['human_gate_8_effect']!r}"
            )
        if record["claim_change"] != "NONE":
            raise DeltaReviewError(
                f"review record claim_change must leave existing proposed claims unchanged "
                f"(NONE): {record['claim_change']!r}"
            )
        if record["gate_8_change"] != "NONE":
            raise DeltaReviewError(
                f"review record gate_8_change must leave Gate 8 unchanged (NONE): "
                f"{record['gate_8_change']!r}"
            )

        if not isinstance(record["candidate_id"], str) or not record["candidate_id"]:
            raise DeltaReviewError(f"review record candidate_id must be a non-empty string: {record['candidate_id']!r}")

        observed_source_ids.add(source_id)

    if observed_source_ids != set(candidate_source_ids):
        missing = set(candidate_source_ids) - observed_source_ids
        extra = observed_source_ids - set(candidate_source_ids)
        raise DeltaReviewError(
            "review records are not exactly one-to-one with candidate sources: "
            f"missing={sorted(missing)!r} extra={sorted(extra)!r}"
        )


# ---------------------------------------------------------------------------
# External create-only publication
# ---------------------------------------------------------------------------


def _validate_run_name(run_name: str) -> None:
    if not isinstance(run_name, str) or not run_name.strip():
        raise DeltaReviewError("run_name must be a non-blank string")
    if "\x00" in run_name:
        raise DeltaReviewError(f"run_name must not contain a NUL byte: {run_name!r}")
    if "/" in run_name or "\\" in run_name:
        raise DeltaReviewError(
            f"run_name must be exactly one safe path component (no separators): {run_name!r}"
        )
    if run_name in (".", ".."):
        raise DeltaReviewError(f"run_name must not be a traversal component: {run_name!r}")


def _assert_no_symlink_ancestry(path: Path, *, role: str) -> None:
    current = path
    while True:
        if current.is_symlink():
            raise DeltaReviewError(
                f"{role} path {path} has a symlink/reparse ancestor at {current}; refusing for "
                "safety"
            )
        parent = current.parent
        if parent == current:
            return
        current = parent


def write_delta_bundle(
    *,
    repo_root: Path,
    output_root: Path,
    run_name: str,
    manifest: dict[str, Any],
    artifact_payloads: dict[str, bytes],
) -> dict[str, Any]:
    """Publish ``manifest`` and ``artifact_payloads`` to
    ``output_root/run_name`` -- external (never resolving inside
    ``repo_root``), create-only (the final run path must not already
    exist), symlink-safe (neither ``output_root``'s ancestry nor the
    final run path may be a symlink/reparse point) and atomic (delegated
    to ``raptor.external.tsc2_sources.bundle._publish_directory_no_
    replace``, this project's hardened no-clobber directory-rename
    primitive). Every artifact payload's bytes are re-verified against its
    manifest-declared ``byte_length``/``sha256`` before any bytes are
    written, and the manifest file itself is always the LAST file written
    into the published run directory. On ANY failure, the staging
    directory is removed and nothing is left at the final run path.
    Raises ``DeltaReviewError`` on any violation."""
    _validate_run_name(run_name)

    recomputed = compute_manifest_content_hash(manifest)
    if manifest.get("content_hash") != recomputed:
        raise DeltaReviewError(
            f"manifest content_hash mismatch: recorded {manifest.get('content_hash')!r} != "
            f"recomputed {recomputed!r}"
        )

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise DeltaReviewError("manifest 'artifacts' must be a non-empty list")

    repo_root = Path(repo_root)
    output_root = Path(output_root)

    _assert_no_symlink_ancestry(output_root, role="output_root")

    resolved_repo_root = repo_root.resolve()
    resolved_output_root = output_root.resolve()
    try:
        resolved_output_root.relative_to(resolved_repo_root)
        inside_repo = True
    except ValueError:
        inside_repo = False
    if inside_repo:
        raise DeltaReviewError(
            f"output_root {output_root} resolves inside repo_root {repo_root}; the external "
            "delta-review bundle must never be written inside the repository"
        )

    final_run_dir = output_root / run_name
    if final_run_dir.is_symlink():
        raise DeltaReviewError(
            f"output run path {final_run_dir} is a symlink/reparse point; refusing for safety"
        )
    if final_run_dir.exists():
        raise DeltaReviewError(
            f"output run path {final_run_dir} already exists; runs are create-only and are "
            "never overwritten or silently resumed"
        )

    output_root.mkdir(parents=True, exist_ok=True)
    # Re-check ancestry AFTER creating output_root: mkdir may have just
    # created one or more ancestor directories, and a TOCTOU window exists
    # between the pre-creation check above and this point.
    _assert_no_symlink_ancestry(output_root, role="output_root")

    staging_dir = output_root / f".{run_name}.staging-{uuid.uuid4().hex}"
    staging_dir.mkdir(parents=False, exist_ok=False)
    try:
        for artifact in artifacts:
            for field in ("relative_path", "byte_length", "sha256"):
                if field not in artifact:
                    raise DeltaReviewError(f"artifact record missing required field {field!r}: {artifact!r}")
            relative_path = artifact["relative_path"]
            destination = _safe_join(staging_dir, relative_path)
            payload = artifact_payloads.get(relative_path)
            if payload is None:
                raise DeltaReviewError(f"missing artifact payload bytes for relative_path {relative_path!r}")
            if len(payload) != artifact["byte_length"]:
                raise DeltaReviewError(
                    f"artifact {relative_path!r} byte_length mismatch: expected "
                    f"{artifact['byte_length']!r}, observed {len(payload)!r} bytes"
                )
            observed_sha256 = _sha256_bytes(payload)
            if observed_sha256.lower() != str(artifact["sha256"]).lower():
                raise DeltaReviewError(
                    f"artifact {relative_path!r} sha256 hash mismatch: expected "
                    f"{artifact['sha256']!r}, observed {observed_sha256!r}"
                )
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)

        manifest_path = staging_dir / MANIFEST_FILENAME
        manifest_path.write_text(_canonical_json(manifest), encoding="utf-8")
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    try:
        _publish_directory_no_replace(staging_dir, final_run_dir)
    except FileExistsError as exc:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise DeltaReviewError(
            f"output run path {final_run_dir} was concurrently created by another writer during "
            "publication; refusing to replace a competing publication"
        ) from exc
    except OSError as exc:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise DeltaReviewError(f"failed to atomically publish run directory {final_run_dir}: {exc}") from exc

    return {"run_dir": final_run_dir, "manifest_path": final_run_dir / MANIFEST_FILENAME}


# ---------------------------------------------------------------------------
# Committed summary
# ---------------------------------------------------------------------------


def build_committed_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    """Re-verify ``manifest``'s own canonical ``content_hash`` FIRST, then
    project a strict, aggregate-only committed summary: the manifest's own
    content hash, ``input_hashes``, ``counts``, ``source_role_counts``,
    ``delta_value_counts``, ``baseline_relation_counts``, a fixed
    ``state`` block (zero accepted claims, Gate 8 still
    ``BLOCKED_HUMAN_REVIEW``, ``human_gate_8_effect`` ``NONE``), the
    manifest's ``boundaries`` block, and ``external_artifact_hashes`` (a
    ``relative_path`` -> ``sha256`` mapping ONLY -- never a full artifact
    record). This is a STRICT field-whitelist projection: it NEVER reads
    or copies a PMID, PMCID, DOI, title, abstract, quote, locator or
    proposed statement, even if such a field is present somewhere else in
    ``manifest``. Raises ``DeltaReviewError`` if ``manifest``'s
    ``content_hash`` does not match its recomputed value."""
    recomputed = compute_manifest_content_hash(manifest)
    stored = manifest.get("content_hash")
    if recomputed != stored:
        raise DeltaReviewError(
            f"manifest content_hash mismatch: recorded {stored!r} != recomputed {recomputed!r}"
        )

    counts = dict(manifest["counts"])
    return {
        "schema": COMMITTED_SUMMARY_SCHEMA,
        "bundle_id": manifest["bundle_id"],
        "manifest_content_hash": manifest["content_hash"],
        "input_hashes": dict(manifest["input_hashes"]),
        "counts": counts,
        "source_role_counts": dict(manifest["source_role_counts"]),
        "delta_value_counts": dict(manifest["delta_value_counts"]),
        "baseline_relation_counts": dict(manifest["baseline_relation_counts"]),
        "state": {
            "accepted_claims": counts.get("accepted_claims", 0),
            "gate_8": "BLOCKED_HUMAN_REVIEW",
            "human_gate_8_effect": "NONE",
        },
        "external_artifact_hashes": {
            artifact["relative_path"]: artifact["sha256"] for artifact in manifest["artifacts"]
        },
        "boundaries": dict(manifest["boundaries"]),
    }


__all__ = [
    "MANIFEST_FILENAME",
    "ARTICLE_INDEX_SCHEMA",
    "CANDIDATE_SPAN_SCHEMA",
    "REVIEW_RECORD_SCHEMA",
    "DELTA_BUNDLE_MANIFEST_SCHEMA",
    "DELTA_PREPARATION_MANIFEST_SCHEMA",
    "COMMITTED_SUMMARY_SCHEMA",
    "CANONICAL_ALIASES",
    "CONDITIONAL_LEGACY_ALIASES",
    "ARTICLE_INDEX_FIELDS",
    "CANDIDATE_SPAN_FIELDS",
    "REVIEW_RECORD_FIELDS",
    "DISPOSITIONS",
    "SOURCE_ROLES",
    "PRIMARY_RESULT_STATES",
    "BASELINE_RELATIONS",
    "DELTA_VALUES",
    "REQUIRED_CONTEXT_FIELDS",
    "DeltaReviewError",
    "compute_manifest_content_hash",
    "validate_acquisition_manifest",
    "extract_jats_blocks",
    "match_aliases",
    "validate_article_dispositions",
    "validate_candidate_spans",
    "validate_review_records",
    "write_delta_bundle",
    "build_committed_summary",
]
