from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "docs" / "project" / "specs" / "raptor-v2-r611q-literature-delta-review-v1.yaml"
PACKAGE_PATH = REPO_ROOT / "src" / "raptor" / "external" / "r611q_literature" / "delta_review.py"
OPERATOR_SCRIPT = REPO_ROOT / "scripts" / "build_r611q_literature_delta_review.py"
CONFIG_PATH = REPO_ROOT / "configs" / "external" / "r611q_literature_delta_review_v1.yaml"
SUMMARY_PATH = REPO_ROOT / "data" / "census" / "r611q_literature_delta_review_2026-09-16.json"
MANIFEST_FILENAME = "bundle_manifest.json"

ARTICLE_INDEX_SCHEMA = "raptor.external.r611q_literature_article.v1"
CANDIDATE_SPAN_SCHEMA = "raptor.external.r611q_literature_delta_candidate_span.v1"
REVIEW_RECORD_SCHEMA = "raptor.external.r611q_literature_delta_review_record.v1"

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

CANONICAL_ALIASES = (
    "rs28934872",
    "c.1832G>A",
    "NM_000548.5:c.1832G>A",
    "p.Arg611Gln",
    "NP_000539.2:p.Arg611Gln",
    "Arg611Gln",
    "p.R611Q",
    "R611Q",
)
CONDITIONAL_LEGACY_ALIASES = ("1832G>A", "G1832A")

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
    {
        "SUPPORTS",
        "NARROWS",
        "CONTRADICTS",
        "ORTHOGONAL",
        "NO_DIRECT_RELATION",
    }
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
REQUIRED_CONTEXT_FIELDS = (
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

FORBIDDEN_IMPORT_PREFIXES = (
    "raptor.scorer",
    "raptor.eval",
    "raptor.packet",
    "raptor.census",
    "raptor.kb",
)
FORBIDDEN_NETWORK_IMPORTS = (
    "socket",
    "requests",
    "httpx",
    "aiohttp",
    "urllib.request",
    "urllib3",
    "http.client",
)

FORBIDDEN_REAL_SNIPPETS = (
    "pmc11185720",
    "10.1101/2024.06.07.597916",
    "42425971",
    "40000001",
    "clinvar_uid",
)
FORBIDDEN_CLASSIFICATION_TERMS = (
    "likely pathogenic",
    "pathogenic",
    "likely benign",
    "benign",
    "uncertain significance",
    "acmg",
)

EXPECTED_SUMMARY_KEYS = frozenset(
    {
        "schema",
        "bundle_id",
        "manifest_content_hash",
        "input_hashes",
        "counts",
        "source_role_counts",
        "delta_value_counts",
        "baseline_relation_counts",
        "state",
        "external_artifact_hashes",
        "boundaries",
    }
)
SUMMARY_FORBIDDEN_KEYS = (
    '"pmid"',
    '"pmcid"',
    '"doi"',
    '"title"',
    '"abstract"',
    '"locator"',
    '"exact_quote"',
    '"proposed_statement"',
    '"reviewer_output"',
)


def _load_module(module_name: str):
    try:
        return import_module(module_name)
    except ImportError as exc:
        pytest.fail(f"R611Q literature delta-review module {module_name!r} is not implemented: {exc}")


def _load_operator_module():
    if not OPERATOR_SCRIPT.is_file():
        pytest.fail(f"R611Q literature delta-review operator is not implemented: {OPERATOR_SCRIPT}")
    spec = importlib.util.spec_from_file_location("build_r611q_literature_delta_review", OPERATOR_SCRIPT)
    if spec is None or spec.loader is None:
        pytest.fail(f"could not load operator module spec from {OPERATOR_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _symbol(module: Any, symbol_name: str):
    if not hasattr(module, symbol_name):
        pytest.fail(
            f"R611Q literature delta-review module {module.__name__!r} is missing public symbol "
            f"{symbol_name!r}"
        )
    return getattr(module, symbol_name)


def _delta_api() -> dict[str, Any]:
    module = _load_module("raptor.external.r611q_literature.delta_review")
    return {
        "DeltaReviewError": _symbol(module, "DeltaReviewError"),
        "compute_manifest_content_hash": _symbol(module, "compute_manifest_content_hash"),
        "validate_acquisition_manifest": _symbol(module, "validate_acquisition_manifest"),
        "extract_jats_blocks": _symbol(module, "extract_jats_blocks"),
        "match_aliases": _symbol(module, "match_aliases"),
        "validate_article_dispositions": _symbol(module, "validate_article_dispositions"),
        "validate_candidate_spans": _symbol(module, "validate_candidate_spans"),
        "validate_review_records": _symbol(module, "validate_review_records"),
        "write_delta_bundle": _symbol(module, "write_delta_bundle"),
        "build_committed_summary": _symbol(module, "build_committed_summary"),
    }


def _iter_python_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def _module_imports(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append((node.module, node.lineno))
    return imports


def _sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _manifest_content_hash(manifest: dict[str, Any]) -> str:
    basis = {key: value for key, value in manifest.items() if key != "content_hash"}
    return _sha256_bytes(_canonical_json(basis).encode("utf-8"))


def _assert_no_cribbing(value: Any) -> None:
    if isinstance(value, str):
        lowered = value.lower()
        for token in FORBIDDEN_REAL_SNIPPETS:
            assert token not in lowered, f"anti-cribbing violation: found prohibited real-data token {token!r}"
        for token in FORBIDDEN_CLASSIFICATION_TERMS:
            assert token not in lowered, f"anti-cribbing violation: found prohibited classification term {token!r}"
        return
    if isinstance(value, dict):
        for key, nested in value.items():
            _assert_no_cribbing(key)
            _assert_no_cribbing(nested)
        return
    if isinstance(value, (list, tuple, set)):
        for nested in value:
            _assert_no_cribbing(nested)


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    return re.sub(r"\s+", " ", normalized).strip()


def _contains_declaration(xml_text: str, token: str) -> bool:
    return token in xml_text.lower()


def _is_descendant(node: ET.Element, ancestor: ET.Element, parent_by_child: dict[ET.Element, ET.Element]) -> bool:
    cursor = node
    while cursor in parent_by_child:
        cursor = parent_by_child[cursor]
        if cursor is ancestor:
            return True
    return False


def _compile_alias_pattern(alias: str) -> re.Pattern[str]:
    escaped = re.escape(alias)
    escaped = escaped.replace(">", r"\s*>\s*")
    return re.compile(rf"(?<![0-9A-Za-z_]){escaped}(?![0-9A-Za-z_])", re.IGNORECASE)


_CANONICAL_PATTERNS = {alias: _compile_alias_pattern(alias) for alias in CANONICAL_ALIASES}
_LEGACY_PATTERNS = {alias: _compile_alias_pattern(alias) for alias in CONDITIONAL_LEGACY_ALIASES}
_CONTEXT_PATTERN = re.compile(r"(?<![0-9A-Za-z_])(tsc2|tuberin)(?![0-9A-Za-z_])", re.IGNORECASE)


def _oracle_match_aliases(text: str) -> list[str]:
    canonical_hits = [alias for alias, pattern in _CANONICAL_PATTERNS.items() if pattern.search(text)]
    context_ok = bool(canonical_hits) or _CONTEXT_PATTERN.search(text) is not None
    legacy_hits = []
    if context_ok:
        legacy_hits = [alias for alias, pattern in _LEGACY_PATTERNS.items() if pattern.search(text)]
    merged = sorted(set(canonical_hits + legacy_hits), key=lambda v: (v.casefold(), v))
    return merged


def _oracle_extract_smallest_matching_blocks(xml_text: str) -> dict[str, Any]:
    if _contains_declaration(xml_text, "<!doctype"):
        raise ValueError("DOCTYPE is forbidden")
    if _contains_declaration(xml_text, "<!entity"):
        raise ValueError("ENTITY is forbidden")

    root = ET.fromstring(xml_text)
    if _local_name(root.tag) != "article":
        raise ValueError("root must be article")
    body = root.find("./body")
    if body is None:
        raise ValueError("article/body is required")

    parent_by_child: dict[ET.Element, ET.Element] = {}
    for parent in body.iter():
        for child in parent:
            parent_by_child[child] = parent

    block_tags = {"p", "td", "th", "caption"}
    blocks: list[tuple[ET.Element, str, str, list[str]]] = []

    def walk(node: ET.Element, excluded: bool = False) -> None:
        tag = _local_name(node.tag)
        next_excluded = excluded or tag == "ref-list"
        if next_excluded:
            return
        if tag in block_tags:
            text = _normalize_text("".join(node.itertext()))
            if text:
                matches = _oracle_match_aliases(text)
                blocks.append((node, tag, text, matches))
        for child in list(node):
            walk(child, excluded=next_excluded)

    walk(body)

    selected: list[tuple[str, str, list[str]]] = []
    for node, tag, text, matches in blocks:
        if not matches:
            continue
        has_matching_descendant = any(
            other_matches and _is_descendant(other_node, node, parent_by_child)
            for other_node, _other_tag, _other_text, other_matches in blocks
            if other_node is not node
        )
        if has_matching_descendant:
            continue
        selected.append((tag, text, matches))

    joined_text_parts: list[str] = []
    records: list[dict[str, Any]] = []
    cursor = 0
    for index, (tag, text, matches) in enumerate(selected):
        joined_text_parts.append(text)
        start = cursor
        end = cursor + len(text)
        records.append(
            {
                "block_index": index,
                "block_tag": tag,
                "locator": f"text-char:{start}:{end}",
                "text": text,
                "matched_aliases": matches,
            }
        )
        cursor = end + 1

    return {"joined_text": "\n".join(joined_text_parts), "blocks": records}


def _slice_locator(text: str, locator: str) -> str:
    match = re.fullmatch(r"text-char:(\d+):(\d+)", locator)
    assert match is not None, f"invalid locator shape: {locator!r}"
    start = int(match.group(1))
    end = int(match.group(2))
    assert start <= end <= len(text), f"locator out of bounds: {locator!r} for len={len(text)}"
    return text[start:end]


def _oracle_candidate_id(article_identity: dict[str, Any], surface: str, block_index: int) -> str:
    basis = {"article_identity": article_identity, "surface": surface, "block_index": block_index}
    return hashlib.sha256(_canonical_json(basis).encode("utf-8")).hexdigest()[:24]


def _oracle_candidate_span(
    *,
    article_identity: dict[str, Any],
    source_artifact_id: str,
    source_artifact_sha256: str,
    surface: str,
    block_index: int,
    block_tag: str,
    locator: str,
    exact_quote: str,
    matched_aliases: list[str],
) -> dict[str, Any]:
    sorted_aliases = sorted(set(matched_aliases), key=lambda v: (v.casefold(), v))
    return {
        "schema": CANDIDATE_SPAN_SCHEMA,
        "candidate_id": _oracle_candidate_id(article_identity, surface, block_index),
        "article_identity": article_identity,
        "source_artifact_id": source_artifact_id,
        "source_artifact_sha256": source_artifact_sha256,
        "surface": surface,
        "block_index": block_index,
        "block_tag": block_tag,
        "locator": locator,
        "exact_quote": exact_quote,
        "exact_quote_sha256": _sha256_bytes(exact_quote.encode("utf-8")),
        "matched_aliases": sorted_aliases,
        "review_state": "PROPOSED_UNACCEPTED",
    }


def _synthetic_article_rows() -> list[dict[str, Any]]:
    rows = [
        {
            "schema": ARTICLE_INDEX_SCHEMA,
            "pmid": "99000001",
            "discovery_sources": ["litvar2", "clinvar"],
            "pubmed_status": "RESOLVED",
            "pmcid": "PMC9900001",
            "doi": "10.9999/syn.0001",
            "title": "Synthetic allele assay study",
            "publication_date": "2026-01-11",
            "publication_date_precision": "day",
            "abstract": "Synthetic abstract without canonical alias.",
            "europe_pmc_status": "RESOLVED",
            "is_open_access": True,
            "licence": "CC BY",
            "fulltext_status": "ACQUIRED_CC_BY",
            "fulltext_artifact_id": "fulltext/PMC9900001.xml",
        },
        {
            "schema": ARTICLE_INDEX_SCHEMA,
            "pmid": "99000002",
            "discovery_sources": ["litvar2"],
            "pubmed_status": "UNRESOLVED",
            "pmcid": None,
            "doi": None,
            "title": None,
            "publication_date": None,
            "publication_date_precision": None,
            "abstract": None,
            "europe_pmc_status": "UNRESOLVED",
            "is_open_access": None,
            "licence": None,
            "fulltext_status": "UNAVAILABLE",
            "fulltext_artifact_id": None,
        },
        {
            "schema": ARTICLE_INDEX_SCHEMA,
            "pmid": "99000003",
            "discovery_sources": ["clinvar"],
            "pubmed_status": "RESOLVED",
            "pmcid": "PMC9900003",
            "doi": "10.9999/syn.0003",
            "title": "Synthetic context-only model note",
            "publication_date": "2026-03",
            "publication_date_precision": "month",
            "abstract": "A model-context abstract with no exact alias token.",
            "europe_pmc_status": "RESOLVED",
            "is_open_access": False,
            "licence": None,
            "fulltext_status": "UNAVAILABLE",
            "fulltext_artifact_id": None,
        },
    ]
    _assert_no_cribbing(rows)
    return rows


def _synthetic_acquisition_bundle(tmp_path: Path) -> dict[str, Any]:
    bundle_root = tmp_path / "acquisition"
    normalized_dir = bundle_root / "normalized"
    fulltext_dir = bundle_root / "fulltext"
    normalized_dir.mkdir(parents=True)
    fulltext_dir.mkdir(parents=True)

    rows = _synthetic_article_rows()
    article_index_body = "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows).encode(
        "utf-8"
    )
    article_index_rel = "normalized/article-index.jsonl"
    article_index_path = bundle_root / article_index_rel
    article_index_path.write_bytes(article_index_body)

    xml_body = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<article><body><sec><p>Synthetic tuberin statement with R611Q token.</p></sec></body></article>"
    ).encode("utf-8")
    xml_rel = "fulltext/PMC9900001.xml"
    xml_path = bundle_root / xml_rel
    xml_path.write_bytes(xml_body)

    artifacts = [
        {
            "artifact_id": "article-index",
            "source_id": "pubmed:99000001",
            "role": "ARTICLE_INDEX",
            "relative_path": article_index_rel,
            "byte_length": len(article_index_body),
            "sha256": _sha256_bytes(article_index_body),
        },
        {
            "artifact_id": "fulltext-9900001",
            "source_id": "pmcid:PMC9900001",
            "role": "FULLTEXT_XML",
            "relative_path": xml_rel,
            "byte_length": len(xml_body),
            "sha256": _sha256_bytes(xml_body),
        },
    ]

    manifest = {
        "schema": "raptor.external.r611q_literature_bundle.v1",
        "bundle_id": "synthetic-r611q-acquisition",
        "artifacts": artifacts,
        "counts": {"sources": 2, "artifacts": len(artifacts)},
        "content_hash": "",
    }
    manifest["content_hash"] = _manifest_content_hash(manifest)
    manifest_bytes = (_canonical_json(manifest) + "\n").encode("utf-8")
    manifest_path = bundle_root / MANIFEST_FILENAME
    manifest_path.write_bytes(manifest_bytes)

    return {
        "bundle_root": bundle_root,
        "manifest": manifest,
        "manifest_path": manifest_path,
        "manifest_file_sha256": _sha256_bytes(manifest_bytes),
        "manifest_byte_length": len(manifest_bytes),
        "article_index_expectation": {
            "relative_path": article_index_rel,
            "sha256": _sha256_bytes(article_index_body),
            "byte_length": len(article_index_body),
            "rows": len(rows),
        },
        "rows": rows,
        "source_hashes": {
            "fulltext/PMC9900001.xml": _sha256_bytes(xml_body),
            "normalized/article-index.jsonl": _sha256_bytes(article_index_body),
        },
    }


def _good_review_records(candidate_id: str) -> tuple[list[dict[str, Any]], set[str], set[str], set[str]]:
    candidate_source_ids = {"PMID:99000001", "PMID:99000003"}
    baseline_source_ids = {"PMID:88000001", "PMID:88000002"}
    proposition_vocab = {"prop-syn-001", "prop-syn-002"}

    records = [
        {
            "schema": REVIEW_RECORD_SCHEMA,
            "source_id": "PMID:99000001",
            "article_identity": {"pmid": "99000001", "pmcid": "PMC9900001", "doi": "10.9999/syn.0001"},
            "candidate_id": candidate_id,
            "source_role": "DIRECT_ALLELE_EXPERIMENT",
            "primary_result_state": "PRIMARY_R611Q_RESULT",
            "baseline_relation": "NARROWS",
            "baseline_claim_id": "r611q-claim-0",
            "delta_value": "NEW_PRIMARY_OBSERVATION",
            "proposition_ids": ["prop-syn-001"],
            "context": {
                "r611q_role": "direct_allele",
                "model_system": "synthetic-cell-line",
                "perturbation": "engineered missense substitution",
                "comparator": "wildtype construct",
                "readout": "synthetic phospho-signal ratio",
                "directness": "direct",
                "assay_lineage": "functional",
                "independence": "independent-cohort",
                "limitations": "single readout",
            },
            "review_kind": "MODEL_ASSISTED_SOURCE_TRIAGE",
            "acceptance_state": "PROPOSED_UNACCEPTED",
            "human_gate_8_effect": "NONE",
            "claim_change": "NONE",
            "gate_8_change": "NONE",
        },
        {
            "schema": REVIEW_RECORD_SCHEMA,
            "source_id": "PMID:99000003",
            "article_identity": {"pmid": "99000003", "pmcid": "PMC9900003", "doi": "10.9999/syn.0003"},
            "candidate_id": candidate_id + "-b",
            "source_role": "NOT_RELEVANT",
            "primary_result_state": "NO_R611Q_RESULT",
            "baseline_relation": "NO_DIRECT_RELATION",
            "baseline_claim_id": None,
            "delta_value": "NO_MATERIAL_DELTA",
            "proposition_ids": [],
            "context": {
                "r611q_role": "none",
                "model_system": "n/a",
                "perturbation": "n/a",
                "comparator": "n/a",
                "readout": "n/a",
                "directness": "none",
                "assay_lineage": "none",
                "independence": "n/a",
                "limitations": "exact alias absent after deterministic extraction",
            },
            "review_kind": "MODEL_ASSISTED_SOURCE_TRIAGE",
            "acceptance_state": "PROPOSED_UNACCEPTED",
            "human_gate_8_effect": "NONE",
            "claim_change": "NONE",
            "gate_8_change": "NONE",
        },
    ]
    _assert_no_cribbing(records)
    return records, candidate_source_ids, baseline_source_ids, proposition_vocab


def test_oracle01_anti_cribbing_guard_accepts_synthetic_fixtures_only() -> None:
    fixture = {
        "article_identity": {"pmid": "99000001", "pmcid": "PMC9900001", "doi": "10.9999/syn.0001"},
        "text": "Synthetic paragraph for deterministic regression checks only.",
        "context": {"label": "synthetic-test-only"},
    }
    _assert_no_cribbing(fixture)


def test_oracle02_secure_jats_oracle_rejects_declarations_and_extracts_smallest_blocks_in_order() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<article>
  <body>
    <sec>
      <p>Noise paragraph with no alias mention.</p>
      <p>Parent carrier <caption>R611Q mention in caption</caption> trailing words.</p>
      <table-wrap>
        <table>
          <tbody>
            <tr><td>The tuberin signal includes c.1832G > A in assay text.</td></tr>
            <tr><th>rs28934872 appears in header context.</th></tr>
          </tbody>
        </table>
      </table-wrap>
      <ref-list>
        <ref><mixed-citation>R611Q inside references must be ignored.</mixed-citation></ref>
      </ref-list>
      <p>Cafe\u0301 control with R611Q normalized form.</p>
    </sec>
  </body>
</article>"""
    extracted = _oracle_extract_smallest_matching_blocks(xml)
    blocks = extracted["blocks"]
    assert [item["block_tag"] for item in blocks] == ["caption", "td", "th", "p"]
    assert "references must be ignored" not in extracted["joined_text"].lower()
    assert "Café control with R611Q normalized form." in extracted["joined_text"]
    for block in blocks:
        assert block["matched_aliases"] == sorted(block["matched_aliases"], key=lambda v: (v.casefold(), v))
        assert _slice_locator(extracted["joined_text"], block["locator"]) == block["text"]

    with pytest.raises(ValueError, match="DOCTYPE"):
        _oracle_extract_smallest_matching_blocks("<!DOCTYPE article><article><body><p>R611Q</p></body></article>")
    with pytest.raises(ValueError, match="ENTITY"):
        _oracle_extract_smallest_matching_blocks(
            "<!ENTITY boom 'x'><article><body><p>R611Q</p></body></article>"
        )
    with pytest.raises(ValueError, match="article/body"):
        _oracle_extract_smallest_matching_blocks("<article><front/></article>")


def test_oracle03_alias_oracle_enforces_boundaries_casefold_and_conditional_legacy_rule() -> None:
    assert _oracle_match_aliases("xR611Qx should not match token boundaries") == []
    assert _oracle_match_aliases("r611q appears with mixed case") == ["R611Q"]
    assert _oracle_match_aliases("The term c.1832G > A is present with spacing.") == ["1832G>A", "c.1832G>A"]
    assert _oracle_match_aliases("Legacy 1832G>A appears without context.") == []
    assert _oracle_match_aliases("Legacy G1832A appears with tuberin context.") == ["G1832A"]
    assert _oracle_match_aliases("Legacy 1832G>A plus R611Q context.") == ["1832G>A", "R611Q"]


def test_oracle04_candidate_oracle_hash_and_locator_are_reproducible() -> None:
    article_identity = {"pmid": "99000001", "pmcid": "PMC9900001", "doi": "10.9999/syn.0001"}
    joined = "alpha\nbeta R611Q sentence\ngamma"
    quote = "beta R611Q sentence"
    locator = "text-char:6:25"
    assert _slice_locator(joined, locator) == quote

    span_a = _oracle_candidate_span(
        article_identity=article_identity,
        source_artifact_id="fulltext/PMC9900001.xml",
        source_artifact_sha256="a" * 64,
        surface="acquired_cc_by_jats_body",
        block_index=1,
        block_tag="p",
        locator=locator,
        exact_quote=quote,
        matched_aliases=["R611Q", "p.R611Q", "R611Q"],
    )
    span_b = _oracle_candidate_span(
        article_identity=article_identity,
        source_artifact_id="fulltext/PMC9900001.xml",
        source_artifact_sha256="a" * 64,
        surface="acquired_cc_by_jats_body",
        block_index=1,
        block_tag="p",
        locator=locator,
        exact_quote=quote,
        matched_aliases=["p.R611Q", "R611Q"],
    )
    assert span_a["candidate_id"] == span_b["candidate_id"]
    assert span_a["matched_aliases"] == ["p.R611Q", "R611Q"]
    assert span_a["exact_quote_sha256"] == _sha256_bytes(quote.encode("utf-8"))
    assert set(span_a) == CANDIDATE_SPAN_FIELDS


def test_ac01_required_surface_files_exist() -> None:
    required = [SPEC_PATH, PACKAGE_PATH, OPERATOR_SCRIPT, CONFIG_PATH]
    missing = [str(path.relative_to(REPO_ROOT)) for path in required if not path.exists()]
    assert not missing, "missing required R611Q literature delta-review surfaces:\n" + "\n".join(missing)


def test_ac02_config_matches_spec_input_pins_and_output_names() -> None:
    if not SPEC_PATH.is_file():
        pytest.fail(f"spec file not found: {SPEC_PATH}")
    if not CONFIG_PATH.is_file():
        pytest.fail(f"config file not found: {CONFIG_PATH}")

    spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    assert isinstance(spec, dict)
    assert isinstance(config, dict)

    assert config["schema"] == "raptor.external.r611q_literature_delta_review_config.v1"
    assert config["bundle_id"] == spec["output"]["external_bundle"]["bundle_id"]
    assert config["run_name"] == spec["output"]["external_bundle"]["run_name"]
    assert config["committed_summary_path"] == spec["output"]["committed_summary"]["path"]
    assert config["output"]["environment_variable"] == spec["output"]["external_bundle"]["root_environment_variable"]

    assert config["inputs"]["acquisition_bundle"]["schema"] == spec["inputs"]["acquisition_bundle"]["schema"]
    assert (
        config["inputs"]["acquisition_bundle"]["manifest_content_hash"]
        == spec["inputs"]["acquisition_bundle"]["manifest_content_hash"]
    )
    assert (
        config["inputs"]["acquisition_bundle"]["manifest_file_sha256"]
        == spec["inputs"]["acquisition_bundle"]["manifest_file_sha256"]
    )
    assert (
        config["inputs"]["acquisition_bundle"]["manifest_byte_length"]
        == spec["inputs"]["acquisition_bundle"]["manifest_byte_length"]
    )
    assert config["inputs"]["acquisition_bundle"]["article_index"] == spec["inputs"]["acquisition_bundle"]["article_index"]
    assert config["inputs"]["rescuescreen_baseline"] == spec["inputs"]["rescuescreen_baseline"]
    assert config["inputs"]["atlas_baseline"] == spec["inputs"]["atlas_baseline"]
    assert config["output"]["artifacts"] == spec["output"]["external_bundle"]["artifacts"]


def test_ac03_static_import_boundaries_and_no_network_imports() -> None:
    if not PACKAGE_PATH.is_file():
        pytest.fail(f"delta-review package module is not implemented: {PACKAGE_PATH}")
    if not OPERATOR_SCRIPT.is_file():
        pytest.fail(f"delta-review operator script is not implemented: {OPERATOR_SCRIPT}")

    forbidden: list[str] = []
    network_forbidden: list[str] = []

    for path in [PACKAGE_PATH, OPERATOR_SCRIPT]:
        for imported, lineno in _module_imports(path):
            if any(imported == blocked or imported.startswith(blocked + ".") for blocked in FORBIDDEN_IMPORT_PREFIXES):
                forbidden.append(f"{path.relative_to(REPO_ROOT)}:{lineno}:{imported}")
            if any(imported == blocked or imported.startswith(blocked + ".") for blocked in FORBIDDEN_NETWORK_IMPORTS):
                network_forbidden.append(f"{path.relative_to(REPO_ROOT)}:{lineno}:{imported}")

    assert not network_forbidden, "offline-only delta review must not import network clients:\n" + "\n".join(
        network_forbidden
    )
    assert not forbidden, "forbidden import boundary crossings:\n" + "\n".join(forbidden)


def test_ac04_validate_acquisition_manifest_self_hash_artifacts_and_article_index_schema(tmp_path: Path) -> None:
    api = _delta_api()
    fx = _synthetic_acquisition_bundle(tmp_path)

    validated = api["validate_acquisition_manifest"](
        manifest_path=fx["manifest_path"],
        bundle_root=fx["bundle_root"],
        expected_manifest_content_hash=fx["manifest"]["content_hash"],
        expected_manifest_file_sha256=fx["manifest_file_sha256"],
        expected_manifest_byte_length=fx["manifest_byte_length"],
        expected_article_index=fx["article_index_expectation"],
    )
    assert validated["manifest"]["bundle_id"] == "synthetic-r611q-acquisition"
    assert validated["article_index_row_count"] == 3

    bad_manifest = json.loads(_canonical_json(fx["manifest"]))
    bad_manifest["artifacts"][0]["sha256"] = "0" * 64
    bad_manifest["content_hash"] = _manifest_content_hash(bad_manifest)
    fx["manifest_path"].write_text(_canonical_json(bad_manifest) + "\n", encoding="utf-8")
    with pytest.raises(api["DeltaReviewError"], match="artifact|sha256|byte_length|mismatch"):
        api["validate_acquisition_manifest"](
            manifest_path=fx["manifest_path"],
            bundle_root=fx["bundle_root"],
            expected_manifest_content_hash=bad_manifest["content_hash"],
            expected_manifest_file_sha256=_sha256_bytes((_canonical_json(bad_manifest) + "\n").encode("utf-8")),
            expected_manifest_byte_length=len((_canonical_json(bad_manifest) + "\n").encode("utf-8")),
            expected_article_index=fx["article_index_expectation"],
        )


def test_ac05_secure_jats_parser_contract_enforces_required_root_body_and_smallest_blocks() -> None:
    api = _delta_api()
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<article>
  <body>
    <sec>
      <p>Parent <caption>R611Q in caption only</caption> tail.</p>
      <p>Legacy 1832G>A with TSC2 context.</p>
      <ref-list><ref><mixed-citation>R611Q in references</mixed-citation></ref></ref-list>
    </sec>
  </body>
</article>"""
    parsed = api["extract_jats_blocks"](xml_text=xml)
    assert isinstance(parsed, dict)
    assert isinstance(parsed["joined_text"], str)
    assert isinstance(parsed["blocks"], list)
    assert [block["block_tag"] for block in parsed["blocks"]] == ["caption", "p"]
    assert "references" not in parsed["joined_text"].lower()
    for block in parsed["blocks"]:
        assert _slice_locator(parsed["joined_text"], block["locator"]) == block["text"]

    with pytest.raises(api["DeltaReviewError"], match="DOCTYPE|declaration"):
        api["extract_jats_blocks"](xml_text="<!DOCTYPE article><article><body><p>R611Q</p></body></article>")
    with pytest.raises(api["DeltaReviewError"], match="ENTITY|declaration"):
        api["extract_jats_blocks"](xml_text="<!ENTITY boom 'x'><article><body><p>R611Q</p></body></article>")
    with pytest.raises(api["DeltaReviewError"], match="article/body|required"):
        api["extract_jats_blocks"](xml_text="<article><front/></article>")


def test_ac06_article_dispositions_cover_every_row_once_and_missing_text_is_not_irrelevant(tmp_path: Path) -> None:
    api = _delta_api()
    fx = _synthetic_acquisition_bundle(tmp_path)

    dispositions = [
        {"article_identity": {"pmid": "99000001", "pmcid": "PMC9900001", "doi": "10.9999/syn.0001"}, "disposition": "EXACT_ALIAS_CANDIDATE"},
        {"article_identity": {"pmid": "99000002", "pmcid": None, "doi": None}, "disposition": "SOURCE_TEXT_UNAVAILABLE"},
        {"article_identity": {"pmid": "99000003", "pmcid": "PMC9900003", "doi": "10.9999/syn.0003"}, "disposition": "NO_EXACT_ALIAS_IN_AVAILABLE_TEXT"},
    ]
    api["validate_article_dispositions"](article_index_rows=fx["rows"], dispositions=dispositions)

    bad = json.loads(_canonical_json(dispositions))
    bad[1]["disposition"] = "IRRELEVANT"
    with pytest.raises(api["DeltaReviewError"], match="irrelevant|disposition|exactly one"):
        api["validate_article_dispositions"](article_index_rows=fx["rows"], dispositions=bad)


def test_ac07_candidate_span_schema_ids_aliases_source_hashes_and_locator_reproduction(tmp_path: Path) -> None:
    api = _delta_api()
    fx = _synthetic_acquisition_bundle(tmp_path)

    joined = "alpha\nbeta R611Q and c.1832 G > A in tuberin context\ngamma"
    quote = "beta R611Q and c.1832 G > A in tuberin context"
    span = _oracle_candidate_span(
        article_identity={"pmid": "99000001", "pmcid": "PMC9900001", "doi": "10.9999/syn.0001"},
        source_artifact_id="fulltext/PMC9900001.xml",
        source_artifact_sha256=fx["source_hashes"]["fulltext/PMC9900001.xml"],
        surface="acquired_cc_by_jats_body",
        block_index=1,
        block_tag="p",
        locator="text-char:6:52",
        exact_quote=quote,
        matched_aliases=["R611Q", "c.1832G>A", "R611Q"],
    )
    candidate_spans = [span]
    api["validate_candidate_spans"](
        candidate_spans=candidate_spans,
        article_index_rows=fx["rows"],
        source_artifact_hashes=fx["source_hashes"],
        joined_surface_text_by_artifact={"fulltext/PMC9900001.xml": joined},
    )
    assert _slice_locator(joined, span["locator"]) == span["exact_quote"]
    assert set(span) == CANDIDATE_SPAN_FIELDS

    bad_spans = json.loads(_canonical_json(candidate_spans))
    bad_spans[0]["matched_aliases"] = ["R611Q", "R611Q"]
    with pytest.raises(api["DeltaReviewError"], match="matched_aliases|sorted|unique|non-empty"):
        api["validate_candidate_spans"](
            candidate_spans=bad_spans,
            article_index_rows=fx["rows"],
            source_artifact_hashes=fx["source_hashes"],
            joined_surface_text_by_artifact={"fulltext/PMC9900001.xml": joined},
        )


def test_ac08_review_record_schema_enums_coverage_collision_and_proposition_vocab_membership() -> None:
    api = _delta_api()
    records, candidate_source_ids, baseline_source_ids, proposition_vocab = _good_review_records("cand-a")

    api["validate_review_records"](
        review_records=records,
        candidate_source_ids=candidate_source_ids,
        baseline_source_ids=baseline_source_ids,
        proposition_vocabulary=proposition_vocab,
        allowed_claim_ids={"r611q-claim-0", "r611q-claim-1"},
    )

    bad_collision = json.loads(_canonical_json(records))
    with pytest.raises(api["DeltaReviewError"], match="collision|baseline"):
        api["validate_review_records"](
            review_records=bad_collision,
            candidate_source_ids=candidate_source_ids,
            baseline_source_ids=baseline_source_ids | {"PMID:99000001"},
            proposition_vocabulary=proposition_vocab,
            allowed_claim_ids={"r611q-claim-0", "r611q-claim-1"},
        )

    bad_prop = json.loads(_canonical_json(records))
    bad_prop[0]["proposition_ids"] = ["prop-not-in-baseline"]
    with pytest.raises(api["DeltaReviewError"], match="proposition|vocabulary"):
        api["validate_review_records"](
            review_records=bad_prop,
            candidate_source_ids=candidate_source_ids,
            baseline_source_ids=baseline_source_ids,
            proposition_vocabulary=proposition_vocab,
            allowed_claim_ids={"r611q-claim-0", "r611q-claim-1"},
        )


def test_ac09_secondary_and_model_context_constraints_and_required_review_state_are_enforced() -> None:
    api = _delta_api()
    records, candidate_source_ids, baseline_source_ids, proposition_vocab = _good_review_records("cand-z")

    bad_secondary = json.loads(_canonical_json(records))
    bad_secondary[1]["source_role"] = "SECONDARY_REVIEW"
    bad_secondary[1]["baseline_relation"] = "SUPPORTS"
    bad_secondary[1]["primary_result_state"] = "SECONDARY_SYNTHESIS_ONLY"
    with pytest.raises(api["DeltaReviewError"], match="SECONDARY_REVIEW|support|contradict"):
        api["validate_review_records"](
            review_records=bad_secondary,
            candidate_source_ids=candidate_source_ids,
            baseline_source_ids=baseline_source_ids,
            proposition_vocabulary=proposition_vocab,
            allowed_claim_ids={"r611q-claim-0", "r611q-claim-1"},
        )

    bad_model_context = json.loads(_canonical_json(records))
    bad_model_context[0]["source_role"] = "ALLELE_BEARING_MODEL_CONTEXT"
    bad_model_context[0]["primary_result_state"] = "PRIMARY_R611Q_RESULT"
    bad_model_context[0]["baseline_relation"] = "SUPPORTS"
    with pytest.raises(api["DeltaReviewError"], match="ALLELE_BEARING_MODEL_CONTEXT|direct|PRIMARY_R611Q_RESULT"):
        api["validate_review_records"](
            review_records=bad_model_context,
            candidate_source_ids=candidate_source_ids,
            baseline_source_ids=baseline_source_ids,
            proposition_vocabulary=proposition_vocab,
            allowed_claim_ids={"r611q-claim-0", "r611q-claim-1"},
        )

    bad_state = json.loads(_canonical_json(records))
    bad_state[0]["review_kind"] = "AUTO_ACCEPTED"
    with pytest.raises(api["DeltaReviewError"], match="MODEL_ASSISTED_SOURCE_TRIAGE|PROPOSED_UNACCEPTED|NONE"):
        api["validate_review_records"](
            review_records=bad_state,
            candidate_source_ids=candidate_source_ids,
            baseline_source_ids=baseline_source_ids,
            proposition_vocabulary=proposition_vocab,
            allowed_claim_ids={"r611q-claim-0", "r611q-claim-1"},
        )


def test_ac10_existing_claims_and_gate8_state_cannot_change() -> None:
    api = _delta_api()
    records, candidate_source_ids, baseline_source_ids, proposition_vocab = _good_review_records("cand-g")

    bad_claim_change = json.loads(_canonical_json(records))
    bad_claim_change[0]["claim_change"] = "MODIFY"
    with pytest.raises(api["DeltaReviewError"], match="claim|unchanged|NONE"):
        api["validate_review_records"](
            review_records=bad_claim_change,
            candidate_source_ids=candidate_source_ids,
            baseline_source_ids=baseline_source_ids,
            proposition_vocabulary=proposition_vocab,
            allowed_claim_ids={"r611q-claim-0", "r611q-claim-1"},
        )

    bad_gate_change = json.loads(_canonical_json(records))
    bad_gate_change[0]["gate_8_change"] = "UNBLOCK"
    with pytest.raises(api["DeltaReviewError"], match="Gate 8|gate_8|unchanged|NONE"):
        api["validate_review_records"](
            review_records=bad_gate_change,
            candidate_source_ids=candidate_source_ids,
            baseline_source_ids=baseline_source_ids,
            proposition_vocabulary=proposition_vocab,
            allowed_claim_ids={"r611q-claim-0", "r611q-claim-1"},
        )


def test_ac11_write_path_is_external_create_only_and_manifest_written_last_without_symlink_escape(tmp_path: Path) -> None:
    api = _delta_api()

    disposition_body = b'{"article":"A","disposition":"EXACT_ALIAS_CANDIDATE"}\n'
    candidates_body = b'{"candidate_id":"cand-a"}\n'
    review_body = b'{"source_id":"PMID:99000001"}\n'
    addendum_body = b"# synthetic addendum\n"
    artifacts = [
        ("normalized/article-dispositions.jsonl", disposition_body),
        ("normalized/candidate-spans.jsonl", candidates_body),
        ("reviewed/review-records.jsonl", review_body),
        ("reviewed/R611Q_LITERATURE_DELTA_ADDENDUM.md", addendum_body),
    ]
    manifest = {
        "schema": "raptor.external.r611q_literature_delta_review_bundle.v1",
        "bundle_id": "synthetic-delta-review-bundle",
        "artifacts": [
            {"relative_path": rel, "byte_length": len(body), "sha256": _sha256_bytes(body)} for rel, body in artifacts
        ],
        "counts": {"artifacts": 4, "candidate_spans": 1, "review_records": 1},
        "content_hash": "",
    }
    manifest["content_hash"] = api["compute_manifest_content_hash"](manifest)
    payloads = {rel: body for rel, body in artifacts}

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    inside_repo = repo_root / "external-root"
    inside_repo.mkdir()
    with pytest.raises(api["DeltaReviewError"], match="external|repository"):
        api["write_delta_bundle"](
            repo_root=repo_root,
            output_root=inside_repo,
            run_name="synthetic-run",
            manifest=manifest,
            artifact_payloads=payloads,
        )

    external_root = tmp_path / "outside-root"
    external_root.mkdir()
    result = api["write_delta_bundle"](
        repo_root=repo_root,
        output_root=external_root,
        run_name="synthetic-run",
        manifest=manifest,
        artifact_payloads=payloads,
    )
    assert (result["run_dir"] / MANIFEST_FILENAME).is_file()
    for rel_path, _body in artifacts:
        assert (result["run_dir"] / rel_path).is_file()

    with pytest.raises(api["DeltaReviewError"], match="exists|create-only"):
        api["write_delta_bundle"](
            repo_root=repo_root,
            output_root=external_root,
            run_name="synthetic-run",
            manifest=manifest,
            artifact_payloads=payloads,
        )

    manifest_escape = json.loads(_canonical_json(manifest))
    manifest_escape["artifacts"][0]["relative_path"] = "../escape.jsonl"
    manifest_escape["content_hash"] = api["compute_manifest_content_hash"](manifest_escape)
    with pytest.raises(api["DeltaReviewError"], match="escape|path|relative"):
        api["write_delta_bundle"](
            repo_root=repo_root,
            output_root=external_root,
            run_name="synthetic-escape",
            manifest=manifest_escape,
            artifact_payloads=payloads,
        )

    symlink_root = tmp_path / "symlink-root"
    symlink_root.mkdir()
    real_target = tmp_path / "symlink-target"
    real_target.mkdir()
    try:
        (symlink_root / "synthetic-link").symlink_to(real_target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable in this environment")
    with pytest.raises(api["DeltaReviewError"], match="symlink|reparse"):
        api["write_delta_bundle"](
            repo_root=repo_root,
            output_root=symlink_root,
            run_name="synthetic-link",
            manifest=manifest,
            artifact_payloads=payloads,
        )

    bad_payloads = dict(payloads)
    bad_payloads["reviewed/review-records.jsonl"] = review_body[:-1]
    with pytest.raises(api["DeltaReviewError"], match="hash|byte|artifact"):
        api["write_delta_bundle"](
            repo_root=repo_root,
            output_root=external_root,
            run_name="synthetic-partial-fail",
            manifest=manifest,
            artifact_payloads=bad_payloads,
        )
    failed_manifest = external_root / "synthetic-partial-fail" / MANIFEST_FILENAME
    assert not failed_manifest.exists(), "manifest must be published last and absent on partial failure"


def test_ac12_committed_summary_is_exact_aggregate_derivation_and_excludes_sensitive_content() -> None:
    api = _delta_api()

    manifest = {
        "schema": "raptor.external.r611q_literature_delta_review_bundle.v1",
        "bundle_id": "synthetic-delta-review-bundle",
        "artifacts": [
            {
                "relative_path": "normalized/article-dispositions.jsonl",
                "byte_length": 81,
                "sha256": "1" * 64,
                "sample_sensitive_row": {
                    "pmid": "99000001",
                    "title": "synthetic hidden article title",
                    "exact_quote": "hidden quote",
                    "locator": "text-char:1:9",
                    "proposed_statement": "hidden proposition",
                },
            }
        ],
        "input_hashes": {
            "acquisition_manifest_content_hash": "a" * 64,
            "acquisition_manifest_file_sha256": "b" * 64,
            "rescuescreen_source_manifest_sha256": "c" * 64,
            "rescuescreen_master_inventory_sha256": "d" * 64,
            "atlas_expert_packet_sha256": "e" * 64,
            "atlas_expert_form_sha256": "f" * 64,
        },
        "counts": {
            "article_rows": 69,
            "exact_alias_candidate_sources": 8,
            "title_or_abstract_candidate_sources": 0,
            "fulltext_body_candidate_sources": 8,
            "acquired_fulltexts_without_exact_alias": 18,
            "sources_without_acquired_fulltext": 43,
            "candidate_span_count": 8,
            "review_record_count": 8,
            "accepted_claims": 0,
        },
        "source_role_counts": {
            "DIRECT_ALLELE_EXPERIMENT": 1,
            "ALLELE_BEARING_MODEL_CONTEXT": 2,
            "CLINICAL_CASE_IDENTITY": 1,
            "SECONDARY_REVIEW": 2,
            "NOT_RELEVANT": 2,
        },
        "delta_value_counts": {
            "NEW_PRIMARY_OBSERVATION": 0,
            "NEW_ASSAY_OR_MODEL_CONTEXT": 2,
            "NEW_CLINICAL_OCCURRENCE": 1,
            "SECONDARY_ONLY": 2,
            "NO_MATERIAL_DELTA": 3,
        },
        "baseline_relation_counts": {
            "SUPPORTS": 0,
            "NARROWS": 1,
            "CONTRADICTS": 0,
            "ORTHOGONAL": 2,
            "NO_DIRECT_RELATION": 5,
        },
        "boundaries": {"clinical_use": "forbidden", "ps3_bs3_use": "forbidden"},
        "content_hash": "",
    }
    manifest["content_hash"] = api["compute_manifest_content_hash"](manifest)

    summary = api["build_committed_summary"](manifest)
    assert set(summary) == EXPECTED_SUMMARY_KEYS
    assert summary["manifest_content_hash"] == manifest["content_hash"]
    assert summary["counts"] == manifest["counts"]
    assert summary["source_role_counts"] == manifest["source_role_counts"]
    assert summary["delta_value_counts"] == manifest["delta_value_counts"]
    assert summary["baseline_relation_counts"] == manifest["baseline_relation_counts"]
    assert summary["state"]["accepted_claims"] == 0
    assert summary["state"]["gate_8"] == "BLOCKED_HUMAN_REVIEW"
    assert summary["state"]["human_gate_8_effect"] == "NONE"
    serialized = _canonical_json(summary).lower()
    for forbidden in SUMMARY_FORBIDDEN_KEYS:
        assert forbidden not in serialized
    assert re.search(r"pmc\d{4,}", serialized, re.IGNORECASE) is None
    assert re.search(r'"10\.\d{4,9}/[^"]+"', serialized, re.IGNORECASE) is None


def test_ac13_pilot_summary_regression_file_is_intentionally_red_until_present_and_count_boundaries_hold() -> None:
    # Intentionally RED until the real pilot summary artifact is produced.
    assert SUMMARY_PATH.is_file(), (
        f"committed summary is required by spec and intentionally RED until pilot: {SUMMARY_PATH}"
    )

    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    assert isinstance(summary, dict)
    assert summary.get("counts", {}).get("article_rows") == 69
    assert summary.get("counts", {}).get("exact_alias_candidate_sources") == 8
    assert summary.get("counts", {}).get("title_or_abstract_candidate_sources") == 0
    assert summary.get("counts", {}).get("fulltext_body_candidate_sources") == 8
    assert summary.get("counts", {}).get("acquired_fulltexts_without_exact_alias") == 18
    assert summary.get("counts", {}).get("sources_without_acquired_fulltext") == 43
    for value in summary.get("counts", {}).values():
        assert isinstance(value, int)
        assert not isinstance(value, bool)
        assert value >= 0

    serialized = _canonical_json(summary).lower()
    for forbidden in SUMMARY_FORBIDDEN_KEYS:
        assert forbidden not in serialized
