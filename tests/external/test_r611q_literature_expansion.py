from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import re
import socket
from importlib import import_module
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "docs" / "project" / "specs" / "raptor-v2-r611q-literature-expansion-v1.yaml"
PACKAGE_ROOT = REPO_ROOT / "src" / "raptor" / "external" / "r611q_literature"
OPERATOR_SCRIPT = REPO_ROOT / "scripts" / "fetch_r611q_literature_expansion.py"
CONFIG_PATH = REPO_ROOT / "configs" / "external" / "r611q_literature_expansion_v1.yaml"
SUMMARY_PATH = REPO_ROOT / "data" / "census" / "r611q_literature_expansion_2026-09-15.json"
MANIFEST_FILENAME = "bundle_manifest.json"

BASELINE_SCHEMA = "rescuescreen.r611q.discovery_shelf_sources.v1"
BASELINE_EXPECTED_PMID_PUBLICATIONS = 31
BASELINE_EXPECTED_DOI_ONLY_PUBLICATIONS = 2

ARTICLE_INDEX_FIELDS = {
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

FORBIDDEN_IMPORT_PREFIXES = (
    "raptor.scorer",
    "raptor.eval",
    "raptor.packet",
    "raptor.census",
    "raptor.kb",
    "raptor.atlas",
    "raptor.rescuescreen",
)

PACKAGE_FORBIDDEN_NETWORK_IMPORTS = (
    "socket",
    "requests",
    "httpx",
    "aiohttp",
    "urllib.request",
    "urllib3",
)

KNOWN_LICENCE_VALUES = {None, "CC BY", "CC BY-NC-ND", "CC BY-NC-SA"}

SUMMARY_TOP_LEVEL_KEYS = {
    "schema",
    "bundle_id",
    "manifest_content_hash",
    "baseline_hashes",
    "source_response_hashes",
    "counts",
    "licence_counts",
    "unresolved_counts",
    "boundaries",
    "fulltext_artifact_hashes",
}

FORBIDDEN_PER_ARTICLE_KEYS = (
    '"pmid"',
    '"pmcid"',
    '"doi"',
    '"title"',
    '"abstract"',
    '"fulltext_artifact_id"',
)

FORBIDDEN_ID_VALUE_PATTERNS = (
    re.compile(r'"(?:pmid:)?\d{4,10}"', re.IGNORECASE),
    re.compile(r'"pmc\d{4,}"', re.IGNORECASE),
    re.compile(r'"10\.\d{4,9}/[^"]+"', re.IGNORECASE),
)

PROBE_COUNT_AXES = (
    "litvar2_pmids",
    "clinvar_pmids",
    "litvar2_clinvar_intersection",
    "discovery_union_pmids",
    "baseline_union_overlap",
    "new_pmid_leads",
    "pubmed_records_returned",
    "pubmed_records_unresolved",
    "pubmed_abstracts",
    "pubmed_pmcids",
    "pubmed_dois",
    "europe_pmc_records_returned",
    "europe_pmc_abstracts",
    "europe_pmc_pmcids",
    "europe_pmc_open_access",
    "licence_cc_by",
    "licence_cc_by_nc_nd",
    "licence_cc_by_nc_sa",
    "licence_absent",
    "fulltext_candidates",
)

ROLLUP_COUNT_AXES = (
    "article_index_rows",
    "fulltext_acquired",
    "sources",
    "artifacts",
)


def _load_module(module_name: str):
    try:
        return import_module(module_name)
    except ImportError as exc:
        pytest.fail(f"R611Q literature module {module_name!r} is not implemented: {exc}")


def _load_operator_module():
    if not OPERATOR_SCRIPT.is_file():
        pytest.fail(f"R611Q literature operator script is not implemented: {OPERATOR_SCRIPT}")
    spec = importlib.util.spec_from_file_location("fetch_r611q_literature_expansion", OPERATOR_SCRIPT)
    if spec is None or spec.loader is None:
        pytest.fail(f"could not load operator module spec from {OPERATOR_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _symbol(module: Any, symbol_name: str):
    if not hasattr(module, symbol_name):
        pytest.fail(
            f"R611Q literature module {module.__name__!r} is missing public symbol "
            f"{symbol_name!r}"
        )
    return getattr(module, symbol_name)


def _endpoint_api() -> dict[str, Any]:
    module = _load_module("raptor.external.r611q_literature.endpoint")
    return {
        "EndpointSecurityError": _symbol(module, "EndpointSecurityError"),
        "TransportValidationError": _symbol(module, "TransportValidationError"),
        "build_litvar_publications_url": _symbol(module, "build_litvar_publications_url"),
        "build_clinvar_esearch_url": _symbol(module, "build_clinvar_esearch_url"),
        "build_clinvar_elink_url": _symbol(module, "build_clinvar_elink_url"),
        "build_pubmed_efetch_url": _symbol(module, "build_pubmed_efetch_url"),
        "build_europe_pmc_core_url": _symbol(module, "build_europe_pmc_core_url"),
        "build_europe_pmc_fulltext_xml_url": _symbol(module, "build_europe_pmc_fulltext_xml_url"),
        "assert_allowed_final_url": _symbol(module, "assert_allowed_final_url"),
        "request_with_transport": _symbol(module, "request_with_transport"),
    }


def _parse_api() -> dict[str, Any]:
    module = _load_module("raptor.external.r611q_literature.parse")
    return {
        "R611QLiteratureParseError": _symbol(module, "R611QLiteratureParseError"),
        "parse_baseline_manifest": _symbol(module, "parse_baseline_manifest"),
        "parse_litvar_publications": _symbol(module, "parse_litvar_publications"),
        "parse_clinvar_uid_esearch": _symbol(module, "parse_clinvar_uid_esearch"),
        "parse_clinvar_pubmed_links": _symbol(module, "parse_clinvar_pubmed_links"),
        "derive_discovery_membership": _symbol(module, "derive_discovery_membership"),
        "parse_pubmed_articles_xml": _symbol(module, "parse_pubmed_articles_xml"),
        "parse_europe_pmc_core": _symbol(module, "parse_europe_pmc_core"),
        "select_cc_by_fulltext_candidates": _symbol(module, "select_cc_by_fulltext_candidates"),
        "parse_cc_by_jats_fulltext": _symbol(module, "parse_cc_by_jats_fulltext"),
        "build_article_index_records": _symbol(module, "build_article_index_records"),
        "to_article_index_jsonl": _symbol(module, "to_article_index_jsonl"),
    }


def _bundle_api() -> dict[str, Any]:
    module = _load_module("raptor.external.r611q_literature.bundle")
    return {
        "BundleBoundaryError": _symbol(module, "BundleBoundaryError"),
        "BundleHashMismatchError": _symbol(module, "BundleHashMismatchError"),
        "build_bundle_manifest": _symbol(module, "build_bundle_manifest"),
        "compute_bundle_content_hash": _symbol(module, "compute_bundle_content_hash"),
        "validate_manifest_hash": _symbol(module, "validate_manifest_hash"),
        "write_bundle_run": _symbol(module, "write_bundle_run"),
        "build_committed_summary": _symbol(module, "build_committed_summary"),
    }


def _forbid_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _no_network(*_args, **_kwargs):
        raise AssertionError("real network access is forbidden in this suite")

    monkeypatch.setattr(socket, "create_connection", _no_network)


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


def _replace_query_params(url: str, updates: dict[str, str]) -> str:
    parts = urlsplit(url)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    params.update(updates)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))


def _sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _md5_bytes(blob: bytes) -> str:
    return hashlib.md5(blob).hexdigest()  # nosec B303 - expected as non-cryptographic artifact id


def _artifact_record(
    *,
    artifact_id: str,
    source_id: str,
    relative_path: str,
    body: bytes,
    role: str = "TEST_ARTIFACT",
) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "source_id": source_id,
        "role": role,
        "requested_url": f"https://example.invalid/{artifact_id}",
        "final_url": f"https://example.invalid/{artifact_id}",
        "http_status": 200,
        "media_type": "application/octet-stream",
        "relative_path": relative_path,
        "byte_length": len(body),
        "sha256": _sha256_bytes(body),
        "md5": _md5_bytes(body),
        "fetched_at": "2026-09-15T00:00:00Z",
        "verification": "HASHED",
    }


def _source_record(
    *,
    source_id: str,
    source_kind: str,
    artifact_ids: list[str],
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_kind": source_kind,
        "lifecycle_state": "STAGED_VERIFIED",
        "access_state": "PUBLIC",
        "licence_state": "PUBLIC_METADATA",
        "permitted_use": "NON_CLINICAL_DISCOVERY",
        "identifiers": {"primary": source_id},
        "artifact_ids": artifact_ids,
        "observations": {"fixture": True},
        "limitations": [],
    }


def _baseline_payload(
    *,
    source_ids: list[str],
    schema: str = BASELINE_SCHEMA,
) -> bytes:
    publications: list[dict[str, Any]] = []
    for index, source_id in enumerate(source_ids):
        publications.append(
            {
                "source_id": source_id,
                "captured_at": f"2026-01-{(index % 28) + 1:02d}",
                "origin": "discovery-shelf",
                "evidence_type": "publication",
                "arbitrary_allowed_metadata": {"slot": index},
            }
        )
    payload = {"schema": schema, "publications": publications}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _pubmed_xml_with_article_ids() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>9101</PMID>
      <Article>
        <ArticleTitle>R611Q index article with full date</ArticleTitle>
        <Abstract>
          <AbstractText>First abstract sentence.</AbstractText>
        </Abstract>
        <ELocationID EIdType="doi">10.9999/SHOULD.BE.IGNORED</ELocationID>
        <Journal><JournalIssue><PubDate><Year>2026</Year><Month>09</Month><Day>15</Day></PubDate></JournalIssue></Journal>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="pubmed">9101</ArticleId>
        <ArticleId IdType="pmc">PMC9101</ArticleId>
        <ArticleId IdType="doi">10.1000/R611Q.9101</ArticleId>
      </ArticleIdList>
      <ReferenceList>
        <Reference>
          <ArticleIdList>
            <ArticleId IdType="pubmed">77777777</ArticleId>
            <ArticleId IdType="doi">10.1111/REFERENCE.SHOULD.BE.IGNORED</ArticleId>
          </ArticleIdList>
        </Reference>
      </ReferenceList>
    </PubmedData>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>9102</PMID>
      <Article>
        <ArticleTitle>R611Q month-level date</ArticleTitle>
        <Abstract>
          <AbstractText>Second abstract sentence.</AbstractText>
        </Abstract>
        <ELocationID EIdType="doi">10.8888/LOCATION.ONLY</ELocationID>
        <Journal><JournalIssue><PubDate><Year>2026</Year><Month>09</Month></PubDate></JournalIssue></Journal>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="pubmed">9102</ArticleId>
        <ArticleId IdType="pmc">PMC9102</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>9103</PMID>
      <Article>
        <ArticleTitle>R611Q medline-date article</ArticleTitle>
        <ELocationID EIdType="doi">10.7777/SHOULD.ALSO.BE.IGNORED</ELocationID>
        <Journal><JournalIssue><PubDate><MedlineDate>2026 Winter</MedlineDate></PubDate></JournalIssue></Journal>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="pubmed">9103</ArticleId>
        <ArticleId IdType="doi">10.1000/R611Q.9103</ArticleId>
      </ArticleIdList>
      <ReferenceList>
        <Reference>
          <ArticleIdList>
            <ArticleId IdType="pmc">PMC88888888</ArticleId>
          </ArticleIdList>
        </Reference>
      </ReferenceList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""


def _pubmed_xml_with_duplicate_pmid() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet>
  <PubmedArticle><MedlineCitation><PMID>9201</PMID><Article><ArticleTitle>A</ArticleTitle><Journal><JournalIssue><PubDate><Year>2026</Year></PubDate></JournalIssue></Journal></Article></MedlineCitation></PubmedArticle>
  <PubmedArticle><MedlineCitation><PMID>9201</PMID><Article><ArticleTitle>B</ArticleTitle><Journal><JournalIssue><PubDate><Year>2026</Year></PubDate></JournalIssue></Journal></Article></MedlineCitation></PubmedArticle>
</PubmedArticleSet>
"""


def _pubmed_xml_with_extra_pmid() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet>
  <PubmedArticle><MedlineCitation><PMID>9301</PMID><Article><ArticleTitle>A</ArticleTitle><Journal><JournalIssue><PubDate><Year>2026</Year></PubDate></JournalIssue></Journal></Article></MedlineCitation></PubmedArticle>
  <PubmedArticle><MedlineCitation><PMID>9302</PMID><Article><ArticleTitle>B</ArticleTitle><Journal><JournalIssue><PubDate><Year>2026</Year></PubDate></JournalIssue></Journal></Article></MedlineCitation></PubmedArticle>
  <PubmedArticle><MedlineCitation><PMID>9399</PMID><Article><ArticleTitle>C</ArticleTitle><Journal><JournalIssue><PubDate><Year>2026</Year></PubDate></JournalIssue></Journal></Article></MedlineCitation></PubmedArticle>
</PubmedArticleSet>
"""


def _europe_pmc_core_payload_dict(
    *,
    bad_open_access: str | None = None,
    bad_licence: str | None = None,
) -> dict[str, Any]:
    return {
        "hitCount": 3,
        "resultList": {
            "result": [
                {
                    "id": "9101",
                    "source": "MED",
                    "pmid": "9101",
                    "pmcid": "PMC9101",
                    "doi": "10.1000/r611q.9101",
                    "title": "R611Q index article with full date",
                    "firstPublicationDate": "2026-09-15",
                    "abstractText": "First abstract sentence.",
                    "isOpenAccess": bad_open_access or "Y",
                    "license": bad_licence or "cc by",
                },
                {
                    "id": "9102",
                    "source": "MED",
                    "pmid": "9102",
                    "pmcid": "PMC9102",
                    "doi": None,
                    "title": "R611Q month-level date",
                    "firstPublicationDate": "2026-09-01",
                    "abstractText": None,
                    "isOpenAccess": "N",
                    "license": "  cC bY-nC-nD  ",
                },
                {
                    "id": "9104",
                    "source": "MED",
                    "pmid": "9104",
                    "pmcid": None,
                    "doi": "10.1000/r611q.9104",
                    "title": "R611Q no OA licence absent",
                    "firstPublicationDate": "2026-09-10",
                    "abstractText": "Fourth abstract sentence.",
                    "isOpenAccess": "N",
                    "license": None,
                },
            ]
        },
    }


def _europe_pmc_core_payload(*, bad_open_access: str | None = None, bad_licence: str | None = None) -> str:
    return json.dumps(
        _europe_pmc_core_payload_dict(
            bad_open_access=bad_open_access,
            bad_licence=bad_licence,
        ),
        sort_keys=True,
        separators=(",", ":"),
    )


def _jats_xml(*, pmcid: str, licence_text: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<article>
  <front>
    <article-meta>
      <article-id pub-id-type="pmcid">{pmcid}</article-id>
      <permissions>
        <license license-type="open-access">
          <license-p>{licence_text}</license-p>
        </license>
      </permissions>
    </article-meta>
  </front>
</article>
"""


def _jats_xml_without_licence_paragraph(*, pmcid: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<article>
  <front>
    <article-meta>
      <article-id pub-id-type="pmcid">{pmcid}</article-id>
      <permissions>
        <license license-type="open-access" />
      </permissions>
    </article-meta>
  </front>
</article>
"""


def _minimal_operator_config() -> dict[str, Any]:
    return {
        "schema": "raptor.external.r611q_literature_expansion_config.v1",
        "config_version": "1.0.1",
        "variant": {
            "gene": "TSC2",
            "rsid": "rs28934872",
            "litvar_id": "litvar@rs28934872##",
            "clinvar_uid": "12397",
        },
        "bundle_id": "r611q-literature-expansion-2026-09-15",
        "run_name": "r611q-literature-expansion-2026-09-15",
        "baseline": {
            "schema": BASELINE_SCHEMA,
            "sha256": "8dd13997581fc06998edd0bc73042ae1e8a059bbd2d0dccef4656da1166d1468",
            "byte_length": 26297,
        },
        "output": {
            "environment_variable": "RAPTOR_R611Q_LITERATURE_ROOT",
        },
        "probe_reference_counts": {key: 0 for key in PROBE_COUNT_AXES},
        "sources": {
            "litvar2_publications": {
                "endpoint": "https://www.ncbi.nlm.nih.gov/research/litvar2-api/variant/get/litvar%40rs28934872%23%23/publications?format=json",
            },
            "clinvar_uid_search": {
                "endpoint": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=clinvar&term=rs28934872&retmode=json&retmax=20&tool=raptor",
            },
            "clinvar_pubmed_links": {
                "endpoint": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi?dbfrom=clinvar&db=pubmed&id=12397&linkname=clinvar_pubmed&retmode=json&tool=raptor",
            },
            "pubmed": {
                "endpoint": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
                "batch_size": 200,
            },
            "europe_pmc": {
                "endpoint": "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                "page_size": 1000,
            },
            "fulltext": {
                "endpoint_template": "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML",
                "allowed_metadata_licences": ["CC BY"],
                "required_jats_licence": "CC BY",
            },
        },
    }


def _assert_aggregate_only_summary(summary: dict[str, Any]) -> None:
    assert set(summary) == SUMMARY_TOP_LEVEL_KEYS
    assert isinstance(summary["manifest_content_hash"], str)
    assert re.fullmatch(r"[0-9a-f]{64}", summary["manifest_content_hash"]) is not None

    for key in ("baseline_hashes", "source_response_hashes"):
        assert isinstance(summary[key], dict)
        assert summary[key]
        for value in summary[key].values():
            assert isinstance(value, str)
            assert re.fullmatch(r"[0-9a-f]{64}", value) is not None

    assert isinstance(summary["fulltext_artifact_hashes"], list)
    assert summary["fulltext_artifact_hashes"] == sorted(summary["fulltext_artifact_hashes"])
    for digest in summary["fulltext_artifact_hashes"]:
        assert isinstance(digest, str)
        assert re.fullmatch(r"[0-9a-f]{64}", digest) is not None

    assert isinstance(summary["counts"], dict)
    for axis in (*PROBE_COUNT_AXES, *ROLLUP_COUNT_AXES):
        assert axis in summary["counts"], f"summary counts missing required axis {axis!r}"
        assert isinstance(summary["counts"][axis], int)
        assert not isinstance(summary["counts"][axis], bool)
        assert summary["counts"][axis] >= 0
    assert "fulltext_candidates" in summary["counts"]
    assert "fulltext_acquired" in summary["counts"]
    assert isinstance(summary["counts"]["fulltext_candidates"], int)
    assert isinstance(summary["counts"]["fulltext_acquired"], int)
    assert summary["counts"]["fulltext_acquired"] == len(summary["fulltext_artifact_hashes"])
    assert summary["counts"]["fulltext_candidates"] >= summary["counts"]["fulltext_acquired"]

    unresolved = summary["unresolved_counts"]
    assert isinstance(unresolved, dict)
    assert unresolved
    for value in unresolved.values():
        assert isinstance(value, int)
        assert not isinstance(value, bool)
        assert value >= 0

    counts = summary["counts"]
    assert (
        counts["litvar2_pmids"] + counts["clinvar_pmids"] - counts["litvar2_clinvar_intersection"]
        == counts["discovery_union_pmids"]
    )
    assert counts["baseline_union_overlap"] + counts["new_pmid_leads"] == counts["discovery_union_pmids"]
    assert counts["pubmed_records_returned"] + counts["pubmed_records_unresolved"] == counts["new_pmid_leads"]
    assert (
        counts["europe_pmc_records_returned"] + unresolved.get("europe_pmc_unresolved_pmids", 0)
        == counts["new_pmid_leads"]
    )
    assert unresolved.get("pubmed_missing_pmids", 0) == counts["pubmed_records_unresolved"]
    assert counts["pubmed_abstracts"] <= counts["pubmed_records_returned"]
    assert counts["pubmed_pmcids"] <= counts["pubmed_records_returned"]
    assert counts["pubmed_dois"] <= counts["pubmed_records_returned"]
    assert counts["europe_pmc_abstracts"] <= counts["europe_pmc_records_returned"]
    assert counts["europe_pmc_pmcids"] <= counts["europe_pmc_records_returned"]
    assert counts["europe_pmc_open_access"] <= counts["europe_pmc_records_returned"]
    assert counts["fulltext_candidates"] <= counts["licence_cc_by"]
    assert counts["fulltext_acquired"] <= counts["fulltext_candidates"]
    assert counts["article_index_rows"] == counts["new_pmid_leads"]
    assert (
        counts["licence_cc_by"]
        + counts["licence_cc_by_nc_nd"]
        + counts["licence_cc_by_nc_sa"]
        + counts["licence_absent"]
        == counts["europe_pmc_records_returned"]
    )

    licence_counts = summary["licence_counts"]
    assert isinstance(licence_counts, dict)
    licence_sum = 0
    for value in licence_counts.values():
        assert isinstance(value, int)
        assert not isinstance(value, bool)
        assert value >= 0
        licence_sum += value
    assert licence_sum == counts["europe_pmc_records_returned"]

    serialized = json.dumps(summary, sort_keys=True)
    lowered = serialized.lower()
    for forbidden_key in FORBIDDEN_PER_ARTICLE_KEYS:
        assert forbidden_key not in lowered
    for pattern in FORBIDDEN_ID_VALUE_PATTERNS:
        assert pattern.search(serialized) is None


def _operator_source_text() -> str:
    if not OPERATOR_SCRIPT.is_file():
        pytest.fail(f"R611Q literature operator script is not implemented: {OPERATOR_SCRIPT}")
    return OPERATOR_SCRIPT.read_text(encoding="utf-8")


def test_ac01_required_surface_files_exist() -> None:
    required = [
        PACKAGE_ROOT / "__init__.py",
        PACKAGE_ROOT / "endpoint.py",
        PACKAGE_ROOT / "parse.py",
        PACKAGE_ROOT / "bundle.py",
        OPERATOR_SCRIPT,
        CONFIG_PATH,
        SPEC_PATH,
    ]
    missing = [str(path.relative_to(REPO_ROOT)) for path in required if not path.exists()]
    assert not missing, "missing required R611Q literature-expansion surfaces:\n" + "\n".join(missing)


def test_ac02_endpoint_builders_and_final_url_binding_are_exact_and_substitution_safe() -> None:
    api = _endpoint_api()

    litvar_url = api["build_litvar_publications_url"](litvar_id="litvar@rs28934872##")
    assert (
        litvar_url
        == "https://www.ncbi.nlm.nih.gov/research/litvar2-api/variant/get/litvar%40rs28934872%23%23/publications?format=json"
    )

    clinvar_esearch_url = api["build_clinvar_esearch_url"](
        rsid="rs28934872",
        retmax=20,
        tool="raptor",
    )
    esearch_parts = urlsplit(clinvar_esearch_url)
    esearch_params = parse_qs(esearch_parts.query, strict_parsing=True)
    assert esearch_parts.scheme == "https"
    assert esearch_parts.netloc == "eutils.ncbi.nlm.nih.gov"
    assert esearch_parts.path == "/entrez/eutils/esearch.fcgi"
    assert esearch_params == {
        "db": ["clinvar"],
        "term": ["rs28934872"],
        "retmode": ["json"],
        "retmax": ["20"],
        "tool": ["raptor"],
    }

    clinvar_elink_url = api["build_clinvar_elink_url"](uid="12397", tool="raptor")
    elink_parts = urlsplit(clinvar_elink_url)
    elink_params = parse_qs(elink_parts.query, strict_parsing=True)
    assert elink_parts.scheme == "https"
    assert elink_parts.netloc == "eutils.ncbi.nlm.nih.gov"
    assert elink_parts.path == "/entrez/eutils/elink.fcgi"
    assert elink_params == {
        "dbfrom": ["clinvar"],
        "db": ["pubmed"],
        "id": ["12397"],
        "linkname": ["clinvar_pubmed"],
        "retmode": ["json"],
        "tool": ["raptor"],
    }

    pubmed_efetch_url = api["build_pubmed_efetch_url"](pmids=["9101", "9102"], tool="raptor")
    efetch_parts = urlsplit(pubmed_efetch_url)
    efetch_params = parse_qs(efetch_parts.query, strict_parsing=True)
    assert efetch_parts.scheme == "https"
    assert efetch_parts.netloc == "eutils.ncbi.nlm.nih.gov"
    assert efetch_parts.path == "/entrez/eutils/efetch.fcgi"
    assert efetch_params == {
        "db": ["pubmed"],
        "rettype": ["abstract"],
        "retmode": ["xml"],
        "tool": ["raptor"],
        "id": ["9101,9102"],
    }

    europe_pmc_core_url = api["build_europe_pmc_core_url"](pmids=["9101", "9102"], page_size=1000)
    europe_parts = urlsplit(europe_pmc_core_url)
    europe_params = parse_qs(europe_parts.query, strict_parsing=True)
    assert europe_parts.scheme == "https"
    assert europe_parts.netloc == "www.ebi.ac.uk"
    assert europe_parts.path == "/europepmc/webservices/rest/search"
    assert europe_params["resultType"] == ["core"]
    assert europe_params["pageSize"] == ["1000"]
    assert europe_params["format"] == ["json"]
    query = europe_params["query"][0]
    assert query == "(EXT_ID:9101 OR EXT_ID:9102) AND SRC:MED"
    assert query != "EXT_ID:(9101 OR 9102) AND SRC:MED"

    fulltext_url = api["build_europe_pmc_fulltext_xml_url"](pmcid="PMC9101")
    assert (
        fulltext_url
        == "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC9101/fullTextXML"
    )

    for url in (
        litvar_url,
        clinvar_esearch_url,
        clinvar_elink_url,
        pubmed_efetch_url,
        europe_pmc_core_url,
        fulltext_url,
    ):
        api["assert_allowed_final_url"](requested_url=url, final_url=url)

    with pytest.raises(api["EndpointSecurityError"], match="host|allow"):
        api["assert_allowed_final_url"](
            requested_url=litvar_url,
            final_url=litvar_url.replace("www.ncbi.nlm.nih.gov", "evil.example.org"),
        )
    with pytest.raises(api["EndpointSecurityError"], match="id|substitution"):
        api["assert_allowed_final_url"](
            requested_url=clinvar_elink_url,
            final_url=_replace_query_params(clinvar_elink_url, {"id": "99999"}),
        )
    with pytest.raises(api["EndpointSecurityError"], match="id|substitution"):
        api["assert_allowed_final_url"](
            requested_url=pubmed_efetch_url,
            final_url=_replace_query_params(pubmed_efetch_url, {"id": "9101,9999"}),
        )
    with pytest.raises(api["EndpointSecurityError"], match="query|substitution"):
        api["assert_allowed_final_url"](
            requested_url=europe_pmc_core_url,
            final_url=_replace_query_params(europe_pmc_core_url, {"query": "EXT_ID:9999"}),
        )
    with pytest.raises(api["EndpointSecurityError"], match="query|substitution"):
        api["assert_allowed_final_url"](
            requested_url=europe_pmc_core_url,
            final_url=_replace_query_params(
                europe_pmc_core_url,
                {"query": "EXT_ID:(9101 OR 9102) AND SRC:MED"},
            ),
        )
    with pytest.raises(api["EndpointSecurityError"], match="pmcid|substitution|path"):
        api["assert_allowed_final_url"](
            requested_url=fulltext_url,
            final_url=fulltext_url.replace("PMC9101", "PMC9999"),
        )


def test_ac03_transport_is_injected_only_and_rejects_malformed_transport_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _endpoint_api()
    _forbid_real_network(monkeypatch)
    requested_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        "?db=clinvar&term=rs28934872&retmode=json&retmax=20&tool=raptor"
    )
    seen: list[str] = []
    body = b'{"ok":true}'

    def fake_transport(url: str) -> dict[str, Any]:
        seen.append(url)
        return {"final_url": url, "http_status": 200, "media_type": "application/json", "body": body}

    fetched = api["request_with_transport"](requested_url=requested_url, transport=fake_transport)
    assert seen == [requested_url]
    assert fetched["requested_url"] == requested_url
    assert fetched["final_url"] == requested_url
    assert fetched["byte_length"] == len(body)
    assert fetched["sha256"] == _sha256_bytes(body)

    bad_cases = [
        lambda url: {"final_url": url, "http_status": 503, "media_type": "application/json", "body": body},
        lambda url: {"final_url": "", "http_status": 200, "media_type": "application/json", "body": body},
        lambda url: {"final_url": url, "http_status": "200", "media_type": "application/json", "body": body},
        lambda _url: {"final_url": requested_url, "http_status": 200, "media_type": "application/json", "body": "{}"},
    ]
    for bad_transport in bad_cases:
        with pytest.raises(api["TransportValidationError"]):
            api["request_with_transport"](requested_url=requested_url, transport=bad_transport)


def test_ac04_baseline_manifest_hash_length_schema_and_publication_counts() -> None:
    api = _parse_api()
    pmid_source_ids = [
        f"PMID:{70000000 + idx}" for idx in range(BASELINE_EXPECTED_PMID_PUBLICATIONS)
    ]
    doi_source_ids = ["DOI:10.1000/R611Q.BASELINE.001", "DOI:10.1000/r611q.baseline.002"]
    payload = _baseline_payload(source_ids=[*pmid_source_ids, *doi_source_ids])
    parsed = api["parse_baseline_manifest"](
        payload_bytes=payload,
        expected_schema=BASELINE_SCHEMA,
        expected_sha256=_sha256_bytes(payload),
        expected_byte_length=len(payload),
        expected_pmid_publications=BASELINE_EXPECTED_PMID_PUBLICATIONS,
        expected_doi_only_publications=BASELINE_EXPECTED_DOI_ONLY_PUBLICATIONS,
    )

    assert parsed["schema"] == BASELINE_SCHEMA
    assert parsed["raw_sha256"] == _sha256_bytes(payload)
    assert parsed["raw_byte_length"] == len(payload)
    assert parsed["pmid_publications"] == sorted(
        [source_id.removeprefix("PMID:") for source_id in pmid_source_ids], key=int
    )
    assert parsed["doi_only_publications"] == sorted(
        [source_id.removeprefix("DOI:").lower() for source_id in doi_source_ids]
    )
    assert parsed["counts"] == {
        "pmid_publications": BASELINE_EXPECTED_PMID_PUBLICATIONS,
        "doi_only_publications": BASELINE_EXPECTED_DOI_ONLY_PUBLICATIONS,
    }


def test_ac04_baseline_manifest_rejects_duplicates_or_malformed_ids(
) -> None:
    api = _parse_api()
    bad_cases = [
        ["PMID:70000001", "PMID:70000001", "DOI:10.1000/a", "DOI:10.1000/b"],
        ["PMID:70000001", "PMID:not-a-number", "DOI:10.1000/a", "DOI:10.1000/b"],
        ["PMID:70000001", "PMCID:PMC7000002", "DOI:10.1000/a", "DOI:10.1000/b"],
        ["PMID:70000001", "PMID:70000002", "DOI:not-a-doi", "DOI:10.1000/b"],
        ["PMID:70000001", "PMID:70000002", "DOI:10.1000/A", "DOI:10.1000/a"],
        ["PMID:70000001", "DOI:10.1000/a"],  # wrong fixed counts
    ]
    for source_ids in bad_cases:
        payload = _baseline_payload(source_ids=source_ids)
        with pytest.raises(
            api["R611QLiteratureParseError"],
            match="duplicate|malformed|pmid|doi|source_id|count|expected",
        ):
            api["parse_baseline_manifest"](
                payload_bytes=payload,
                expected_schema=BASELINE_SCHEMA,
                expected_sha256=_sha256_bytes(payload),
                expected_byte_length=len(payload),
                expected_pmid_publications=BASELINE_EXPECTED_PMID_PUBLICATIONS,
                expected_doi_only_publications=BASELINE_EXPECTED_DOI_ONLY_PUBLICATIONS,
            )


def test_ac05_parse_litvar_clinvar_and_union_subtraction_is_deterministic_and_preserves_missing_leads() -> None:
    api = _parse_api()
    litvar_payload = json.dumps(
        {
            "pmids": [9101, "9102", 9102, 99999999],
            "pmcids": ["PMC9101", "PMC9102", "PMC9102"],
            "pmids_count": 3,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    litvar = api["parse_litvar_publications"](litvar_payload)
    assert set(litvar) == {"pmids", "pmcids", "pmid_count", "pmcid_count"}
    assert litvar["pmids"] == ["9101", "9102", "99999999"]
    assert litvar["pmcids"] == ["PMC9101", "PMC9102"]
    assert litvar["pmid_count"] == 3

    clinvar_uid_payload = json.dumps(
        {"esearchresult": {"count": "1", "idlist": ["12397"]}},
        sort_keys=True,
        separators=(",", ":"),
    )
    clinvar_uid = api["parse_clinvar_uid_esearch"](clinvar_uid_payload, expected_uid="12397")
    assert clinvar_uid == "12397"

    clinvar_links_payload = json.dumps(
        {
            "linksets": [
                {
                    "ids": ["12397"],
                    "linksetdbs": [
                        {"dbto": "pubmed", "linkname": "clinvar_pubmed", "links": ["9102", "9103", "9103"]}
                    ],
                }
            ]
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    clinvar_links = api["parse_clinvar_pubmed_links"](clinvar_links_payload, expected_uid="12397")
    assert clinvar_links == ["9102", "9103"]

    derived = api["derive_discovery_membership"](
        litvar_pmids=litvar["pmids"],
        clinvar_pmids=clinvar_links,
        baseline_pmids=["9103"],
    )
    assert derived["litvar2_pmids"] == 3
    assert derived["clinvar_pmids"] == 2
    assert derived["intersection_pmids"] == 1
    assert derived["union_pmids"] == 4
    assert derived["new_pmids"] == ["9101", "9102", "99999999"]
    assert derived["source_membership"]["9102"] == ["litvar2", "clinvar"]
    assert "99999999" in derived["new_pmids"]


def test_ac05_parse_litvar_rejects_malformed_ids() -> None:
    api = _parse_api()
    bad_payloads = [
        {"pmids": [9101], "pmcids": ["PMC9101"]},  # missing pmids_count
        {"pmids": [9101], "pmcids": ["PMC9101"], "pmids_count": 1, "extra": True},  # extra key
        {"pmids": [9101], "pmcids": ["PMC9101"], "pmids_count": True},  # bool invalid
        {"pmids": [9101], "pmcids": ["PMC9101"], "pmids_count": "1"},  # string invalid
        {"pmids": ["9101"], "pmcids": ["PMC9101"], "pmids_count": -1},  # negative invalid
        {"pmids": [9101, "9101"], "pmcids": ["PMC9101"], "pmids_count": 2},  # count drift from unique normalized PMID set
        {"pmids": [True], "pmcids": ["PMC9101"], "pmids_count": 1},  # bool PMID invalid
        {"pmids": [0], "pmcids": ["PMC9101"], "pmids_count": 1},  # non-positive PMID invalid
        {"pmids": [-5], "pmcids": ["PMC9101"], "pmids_count": 1},  # non-positive PMID invalid
        {"pmids": [9101.0], "pmcids": ["PMC9101"], "pmids_count": 1},  # float PMID invalid
        {"pmids": ["91O1"], "pmcids": ["PMC9101"], "pmids_count": 1},  # non-decimal string PMID invalid
        {"pmids": [9101, "bad"], "pmcids": ["PMC9101"], "pmids_count": 2},  # malformed PMID
        {"pmids": [9101], "pmcids": ["PMC9101", "bad-pmcid"], "pmids_count": 1},  # malformed PMCID
    ]
    for payload_obj in bad_payloads:
        payload = json.dumps(payload_obj, sort_keys=True, separators=(",", ":"))
        with pytest.raises(
            api["R611QLiteratureParseError"],
            match="pmid|pmcid|malformed|pmids_count|count|keys|field|exact",
        ):
            api["parse_litvar_publications"](payload)


def test_ac06_pubmed_xml_parser_adds_article_level_fields_preserves_partial_dates_and_reports_requested_missing() -> None:
    api = _parse_api()
    parsed = api["parse_pubmed_articles_xml"](
        _pubmed_xml_with_article_ids(),
        expected_pmids=["9101", "9102", "9103", "9104"],
    )
    assert set(parsed) == {"articles", "requested_but_missing_pmids"}
    assert parsed["requested_but_missing_pmids"] == ["9104"]
    rows = parsed["articles"]
    assert [row["pmid"] for row in rows] == ["9101", "9102", "9103"]

    row_by_pmid = {row["pmid"]: row for row in rows}
    assert row_by_pmid["9101"]["pmcid"] == "PMC9101"
    assert row_by_pmid["9101"]["doi"] == "10.1000/r611q.9101"
    assert row_by_pmid["9101"]["title"] == "R611Q index article with full date"
    assert row_by_pmid["9101"]["publication_date"] == "2026-09-15"

    assert row_by_pmid["9102"]["pmcid"] == "PMC9102"
    assert row_by_pmid["9102"]["doi"] is None
    assert row_by_pmid["9102"]["publication_date"] == "2026-09"
    assert str(row_by_pmid["9102"]["publication_date_precision"]).lower() in {
        "month",
        "year-month",
        "yyyy-mm",
    }

    assert row_by_pmid["9103"]["pmcid"] is None
    assert row_by_pmid["9103"]["doi"] == "10.1000/r611q.9103"
    assert row_by_pmid["9103"]["publication_date"] == "2026 Winter"
    assert str(row_by_pmid["9103"]["publication_date_precision"]).lower() in {
        "medline",
        "medline-date",
        "medlinedate",
        "text",
    }
    assert "77777777" not in row_by_pmid
    assert "88888888" not in row_by_pmid


def test_ac06_pubmed_xml_parser_rejects_duplicate_or_extra_pmids(
) -> None:
    api = _parse_api()
    bad_cases = [
        (_pubmed_xml_with_duplicate_pmid(), ["9201"]),
        (_pubmed_xml_with_extra_pmid(), ["9301", "9302"]),
    ]
    for xml_text, expected_pmids in bad_cases:
        with pytest.raises(api["R611QLiteratureParseError"], match="duplicate|extra|pmid"):
            api["parse_pubmed_articles_xml"](xml_text, expected_pmids=expected_pmids)


def test_ac07_europe_pmc_core_parser_tracks_requested_subset_and_normalizes_known_licences_only() -> None:
    api = _parse_api()
    parsed = api["parse_europe_pmc_core"](
        _europe_pmc_core_payload(),
        requested_pmids=["9101", "9102", "9103", "9104"],
    )
    assert set(parsed) == {"records", "requested_but_unresolved_pmids", "counts"}
    assert parsed["requested_but_unresolved_pmids"] == ["9103"]

    rows = parsed["records"]
    assert [row["pmid"] for row in rows] == ["9101", "9102", "9104"]
    assert all(row["pmid"].isdigit() for row in rows)
    assert all(row["is_open_access"] in {"Y", "N"} for row in rows)
    assert all(row["licence"] in KNOWN_LICENCE_VALUES for row in rows)
    by_pmid = {row["pmid"]: row for row in rows}
    assert by_pmid["9101"]["licence"] == "CC BY"
    assert by_pmid["9102"]["licence"] == "CC BY-NC-ND"
    assert by_pmid["9104"]["licence"] is None

    mixed_case = _europe_pmc_core_payload_dict()
    mixed_case["resultList"]["result"][0]["license"] = " cC bY-Nc-sA "
    mixed_case["resultList"]["result"][2]["license"] = " cc by "
    normalized = api["parse_europe_pmc_core"](
        json.dumps(mixed_case, sort_keys=True, separators=(",", ":")),
        requested_pmids=["9101", "9102", "9103", "9104"],
    )
    normalized_by_pmid = {row["pmid"]: row for row in normalized["records"]}
    assert normalized_by_pmid["9101"]["licence"] == "CC BY-NC-SA"
    assert normalized_by_pmid["9102"]["licence"] == "CC BY-NC-ND"
    assert normalized_by_pmid["9104"]["licence"] == "CC BY"
    assert parsed["counts"]["records_returned"] == 3
    assert parsed["counts"]["pmcid_count"] == 2
    assert parsed["counts"]["abstract_count"] == 2


def test_ac07_europe_pmc_core_parser_rejects_invalid_open_access_or_licence(
) -> None:
    api = _parse_api()
    bad_cases = [("YES", None), (None, "CC BY-SA"), (None, "ccby"), (None, "cc by 4.0"), (None, "cc by nd")]
    for bad_open_access, bad_licence in bad_cases:
        with pytest.raises(api["R611QLiteratureParseError"], match="open|access|licen"):
            api["parse_europe_pmc_core"](
                _europe_pmc_core_payload(bad_open_access=bad_open_access, bad_licence=bad_licence),
                requested_pmids=["9101", "9102", "9103", "9104"],
            )

    non_string_case = _europe_pmc_core_payload_dict()
    non_string_case["resultList"]["result"][0]["license"] = 123
    with pytest.raises(api["R611QLiteratureParseError"], match="licen|type|string"):
        api["parse_europe_pmc_core"](
            json.dumps(non_string_case, sort_keys=True, separators=(",", ":")),
            requested_pmids=["9101", "9102", "9103", "9104"],
        )


def test_ac07_europe_pmc_core_parser_rejects_hitcount_source_identity_and_field_drift() -> None:
    api = _parse_api()
    baseline = _europe_pmc_core_payload_dict()
    bad_cases = []

    case = json.loads(json.dumps(baseline))
    case["hitCount"] = "3"
    bad_cases.append(case)

    case = json.loads(json.dumps(baseline))
    case["hitCount"] = -1
    bad_cases.append(case)

    case = json.loads(json.dumps(baseline))
    case["resultList"]["result"][0]["source"] = "PMC"
    bad_cases.append(case)

    case = json.loads(json.dumps(baseline))
    case["resultList"]["result"][0]["id"] = "9199"
    case["resultList"]["result"][0]["pmid"] = "9101"
    bad_cases.append(case)

    case = json.loads(json.dumps(baseline))
    case["resultList"]["result"][0]["doi"] = "NOT-A-DOI"
    bad_cases.append(case)

    case = json.loads(json.dumps(baseline))
    case["resultList"]["result"][0]["doi"] = "10.1000/UPPER.CASE"
    bad_cases.append(case)

    case = json.loads(json.dumps(baseline))
    case["resultList"]["result"][0]["title"] = 123
    bad_cases.append(case)

    case = json.loads(json.dumps(baseline))
    case["resultList"]["result"][0]["abstractText"] = {"x": 1}
    bad_cases.append(case)

    for case_payload in bad_cases:
        with pytest.raises(api["R611QLiteratureParseError"], match="hitcount|source|id|pmid|doi|title|abstract|type"):
            api["parse_europe_pmc_core"](
                json.dumps(case_payload, sort_keys=True, separators=(",", ":")),
                requested_pmids=["9101", "9102", "9103", "9104"],
            )


def test_ac08_cc_by_candidate_selection_and_jats_parser_enforce_exact_cc_by_only() -> None:
    api = _parse_api()
    parsed_core = api["parse_europe_pmc_core"](
        _europe_pmc_core_payload(),
        requested_pmids=["9101", "9102", "9103", "9104"],
    )
    canonical_records = parsed_core["records"]
    canonical_candidates = api["select_cc_by_fulltext_candidates"](canonical_records)
    assert canonical_candidates == ["PMC9101"]

    records = [
        {"pmid": "9101", "pmcid": "PMC9101", "licence": "CC BY", "is_open_access": "Y"},
        {"pmid": "9102", "pmcid": "PMC9102", "licence": "CC BY", "is_open_access": "N"},
        {"pmid": "9103", "pmcid": None, "licence": "CC BY", "is_open_access": "Y"},
        {"pmid": "9104", "pmcid": "9104", "licence": "CC BY", "is_open_access": "Y"},
        {"pmid": "9105", "pmcid": "PMC9105", "licence": "CC BY-NC", "is_open_access": "Y"},
        {"pmid": "9106", "pmcid": "PMC9106", "licence": "CC BY-ND", "is_open_access": "Y"},
        {"pmid": "9107", "pmcid": "PMC9107", "licence": "CC BY-SA", "is_open_access": "Y"},
        {"pmid": "9108", "pmcid": "PMC9108", "licence": "CC BY-NC-ND", "is_open_access": "Y"},
        {"pmid": "9109", "pmcid": "PMC9109", "licence": None, "is_open_access": "Y"},
    ]
    candidates = api["select_cc_by_fulltext_candidates"](records)
    assert candidates == ["PMC9101"]

    positive_texts = [
        "Distributed under the Creative Commons Attribution License (CC BY 4.0).",
        "THIS ARTICLE IS LICENSED UNDER CREATIVE COMMONS ATTRIBUTION 4.0 INTERNATIONAL.",
        "License URL: https://creativecommons.org/licenses/by/4.0/",
    ]
    for licence_text in positive_texts:
        parsed = api["parse_cc_by_jats_fulltext"](
            _jats_xml(pmcid="PMC9101", licence_text=licence_text),
            expected_pmcid="PMC9101",
        )
        assert parsed["pmcid"] == "PMC9101"
        assert parsed["licence_text"]

    negative_licences = [
        "Distributed under CC BY-NC 4.0.",
        "Distributed under CC BY-ND 4.0.",
        "Distributed under CC BY-SA 4.0.",
        "Distributed under CC BY-NC-ND 4.0.",
        "Distributed under the Creative Commons Attribution-NonCommercial License.",
        "Distributed under the Creative Commons Attribution-NoDerivatives License.",
        "Distributed under the Creative Commons Attribution-ShareAlike License.",
        "License URL: https://creativecommons.org/licenses/by-nc/4.0/",
        "License URL: https://creativecommons.org/licenses/by-nd/4.0/",
        "License URL: https://creativecommons.org/licenses/by-sa/4.0/",
    ]
    for licence_text in negative_licences:
        with pytest.raises(api["R611QLiteratureParseError"], match="NC|ND|SA|CC BY|license|licence"):
            api["parse_cc_by_jats_fulltext"](
                _jats_xml(pmcid="PMC9101", licence_text=licence_text),
                expected_pmcid="PMC9101",
            )

    with pytest.raises(api["R611QLiteratureParseError"], match="license|licence|explicit"):
        api["parse_cc_by_jats_fulltext"](
            _jats_xml_without_licence_paragraph(pmcid="PMC9101"),
            expected_pmcid="PMC9101",
        )

    with pytest.raises(api["R611QLiteratureParseError"], match="pmcid|expected"):
        api["parse_cc_by_jats_fulltext"](
            _jats_xml(
                pmcid="PMC9999",
                licence_text="Distributed under the Creative Commons Attribution License (CC BY 4.0).",
            ),
            expected_pmcid="PMC9101",
        )


def test_ac08_jats_error_typing_contract_and_operator_catches_only_licence_rejections() -> None:
    parse_module = _load_module("raptor.external.r611q_literature.parse")
    parse_api = _parse_api()
    base_error = parse_api["R611QLiteratureParseError"]
    assert hasattr(parse_module, "JatsLicenceRejectedError")
    assert hasattr(parse_module, "JatsIdentityError")
    licence_error = getattr(parse_module, "JatsLicenceRejectedError")
    identity_error = getattr(parse_module, "JatsIdentityError")
    assert issubclass(licence_error, base_error)
    assert issubclass(identity_error, base_error)
    assert licence_error is not identity_error

    with pytest.raises(licence_error):
        parse_api["parse_cc_by_jats_fulltext"](
            _jats_xml_without_licence_paragraph(pmcid="PMC9101"),
            expected_pmcid="PMC9101",
        )
    with pytest.raises(licence_error):
        parse_api["parse_cc_by_jats_fulltext"](
            _jats_xml(
                pmcid="PMC9101",
                licence_text="Distributed under CC BY-NC 4.0.",
            ),
            expected_pmcid="PMC9101",
        )
    with pytest.raises(identity_error):
        parse_api["parse_cc_by_jats_fulltext"](
            "<article><front><article-meta></front></article>",
            expected_pmcid="PMC9101",
        )
    with pytest.raises(identity_error):
        parse_api["parse_cc_by_jats_fulltext"](
            _jats_xml(
                pmcid="PMC9999",
                licence_text="Distributed under the Creative Commons Attribution License (CC BY 4.0).",
            ),
            expected_pmcid="PMC9101",
        )


def test_ac09_article_index_jsonl_is_deterministic_has_exact_fields_and_one_row_per_lead() -> None:
    api = _parse_api()
    new_pmids = ["9101", "9102", "9104"]
    source_membership = {
        "9101": ["litvar2", "clinvar"],
        "9102": ["litvar2"],
        "9104": ["clinvar"],
    }
    pubmed_articles = [
        {
            "pmid": "9101",
            "pmcid": "PMC9101",
            "doi": "10.1000/R611Q.9101",
            "title": "R611Q index article with full date",
            "publication_date": "2026-09-15",
            "publication_date_precision": "day",
            "abstract": "First abstract sentence.",
        },
        {
            "pmid": "9102",
            "pmcid": None,
            "doi": None,
            "title": "R611Q month-level date",
            "publication_date": "2026-09",
            "publication_date_precision": "month",
            "abstract": "Second abstract sentence.",
        },
    ]
    europe_pmc_records = [
        {
            "pmid": "9101",
            "is_open_access": "Y",
            "licence": "CC BY",
            "pmcid": "PMC9101",
            "doi": None,
        },
        {
            "pmid": "9102",
            "is_open_access": "N",
            "licence": "CC BY-NC-ND",
            "pmcid": "PMC9102",
            "doi": "10.1000/R611Q.9102",
        },
    ]
    rows = api["build_article_index_records"](
        new_pmids=new_pmids,
        source_membership=source_membership,
        pubmed_articles=pubmed_articles,
        europe_pmc_records=europe_pmc_records,
        fulltext_status_by_pmcid={"PMC9101": {"fulltext_status": "ACQUIRED_CC_BY", "artifact_id": "fulltext-PMC9101"}},
    )
    assert [row["pmid"] for row in rows] == ["9101", "9102", "9104"]
    assert len(rows) == 3
    for row in rows:
        assert set(row) == ARTICLE_INDEX_FIELDS
        for forbidden in ("claim", "classification", "evidence_strength", "pathogenicity"):
            assert forbidden not in row

    unresolved = [row for row in rows if row["pmid"] == "9104"][0]
    assert unresolved["pubmed_status"] != "RESOLVED"
    assert unresolved["title"] is None
    assert unresolved["abstract"] is None
    by_pmid = {row["pmid"]: row for row in rows}
    assert by_pmid["9101"]["doi"] == "10.1000/r611q.9101"
    assert by_pmid["9102"]["pmcid"] == "PMC9102"
    assert by_pmid["9102"]["doi"] == "10.1000/r611q.9102"

    jsonl_a = api["to_article_index_jsonl"](rows)
    jsonl_b = api["to_article_index_jsonl"](list(reversed(rows)))
    assert jsonl_a == jsonl_b
    lines = [line for line in jsonl_a.splitlines() if line.strip()]
    assert len(lines) == 3
    assert all(set(json.loads(line)) == ARTICLE_INDEX_FIELDS for line in lines)

    bad_memberships = [
        {"9101": ["clinvar", "litvar2"], "9102": ["litvar2"], "9104": ["clinvar"]},  # out of order
        {"9101": ["litvar2", "litvar2"], "9102": ["litvar2"], "9104": ["clinvar"]},  # duplicate source
        {"9101": ["litvar2", "other"], "9102": ["litvar2"], "9104": ["clinvar"]},  # unknown source
        {"9101": ["litvar2", "clinvar"], "9102": ["litvar2"]},  # missing PMID coverage
        {"9101": ["litvar2", "clinvar"], "9102": ["litvar2"], "9104": ["clinvar"], "9999": ["clinvar"]},  # extra PMID
    ]
    for membership in bad_memberships:
        with pytest.raises(api["R611QLiteratureParseError"], match="source_membership|membership|subset|ordered|new_pmids"):
            api["build_article_index_records"](
                new_pmids=new_pmids,
                source_membership=membership,
                pubmed_articles=pubmed_articles,
                europe_pmc_records=europe_pmc_records,
                fulltext_status_by_pmcid={},
            )

    conflict_cases = [
        (
            [{"pmid": "9101", "pmcid": "PMC9101", "doi": "10.1000/r611q.9101", "title": "A", "publication_date": "2026-09-15", "publication_date_precision": "day", "abstract": "a"}],
            [{"pmid": "9101", "is_open_access": "Y", "licence": "CC BY", "pmcid": "PMC9999", "doi": None}],
        ),
        (
            [{"pmid": "9101", "pmcid": "PMC9101", "doi": "10.1000/r611q.9101", "title": "A", "publication_date": "2026-09-15", "publication_date_precision": "day", "abstract": "a"}],
            [{"pmid": "9101", "is_open_access": "Y", "licence": "CC BY", "pmcid": "PMC9101", "doi": "10.1000/r611q.other"}],
        ),
    ]
    for pubmed_rows, epmc_rows in conflict_cases:
        with pytest.raises(api["R611QLiteratureParseError"], match="conflict|pmcid|doi|identity"):
            api["build_article_index_records"](
                new_pmids=["9101"],
                source_membership={"9101": ["litvar2"]},
                pubmed_articles=pubmed_rows,
                europe_pmc_records=epmc_rows,
                fulltext_status_by_pmcid={},
            )

    rejected_rows = api["build_article_index_records"](
        new_pmids=["9101"],
        source_membership={"9101": ["litvar2"]},
        pubmed_articles=[
            {
                "pmid": "9101",
                "pmcid": "PMC9101",
                "doi": "10.1000/r611q.9101",
                "title": "A",
                "publication_date": "2026-09-15",
                "publication_date_precision": "day",
                "abstract": "a",
            }
        ],
        europe_pmc_records=[
            {"pmid": "9101", "is_open_access": "Y", "licence": "CC BY", "pmcid": "PMC9101", "doi": None}
        ],
        fulltext_status_by_pmcid={"PMC9101": {"fulltext_status": "JATS_LICENCE_REJECTED", "artifact_id": None}},
    )
    assert rejected_rows[0]["fulltext_status"] == "JATS_LICENCE_REJECTED"
    assert rejected_rows[0]["fulltext_status"] != "NOT_ELIGIBLE"

    bad_index_cases = [
        {
            "new_pmids": ["9101", "9101"],  # duplicate new PMID
            "pubmed_articles": pubmed_articles,
            "europe_pmc_records": europe_pmc_records,
            "fulltext_status_by_pmcid": {},
        },
        {
            "new_pmids": ["9101"],
            "pubmed_articles": [
                {
                    "pmid": "9101",
                    "pmcid": "PMC9101",
                    "doi": "10.1000/r611q.9101",
                    "title": "A",
                    "publication_date": "2026-09-15",
                    "publication_date_precision": "day",
                    "abstract": "a",
                },
                {
                    "pmid": "9101",
                    "pmcid": "PMC9101",
                    "doi": "10.1000/r611q.9101",
                    "title": "B",
                    "publication_date": "2026-09-15",
                    "publication_date_precision": "day",
                    "abstract": "b",
                },
            ],  # duplicate PubMed record
            "europe_pmc_records": [],
            "fulltext_status_by_pmcid": {},
        },
        {
            "new_pmids": ["9101"],
            "pubmed_articles": [
                {
                    "pmid": "9101",
                    "pmcid": "PMC9101",
                    "doi": "10.1000/r611q.9101",
                    "title": "A",
                    "publication_date": "2026-09-15",
                    "publication_date_precision": "day",
                    "abstract": "a",
                }
            ],
            "europe_pmc_records": [
                {"pmid": "9101", "is_open_access": "Y", "licence": "CC BY", "pmcid": "PMC9101", "doi": None},
                {"pmid": "9101", "is_open_access": "Y", "licence": "CC BY", "pmcid": "PMC9101", "doi": None},
            ],  # duplicate Europe PMC record
            "fulltext_status_by_pmcid": {},
        },
        {
            "new_pmids": ["9101"],
            "pubmed_articles": [
                {
                    "pmid": "9101",
                    "pmcid": "PMC9101",
                    "doi": "10.1000/r611q.9101",
                    "title": "A",
                    "publication_date": "2026-09-15",
                    "publication_date_precision": "day",
                    "abstract": "a",
                }
            ],
            "europe_pmc_records": [],
            "fulltext_status_by_pmcid": {"PMC9999": {"fulltext_status": "ACQUIRED_CC_BY", "artifact_id": "ft-x"}},  # unknown PMCID
        },
        {
            "new_pmids": ["9101"],
            "pubmed_articles": [
                {
                    "pmid": "9101",
                    "pmcid": "PMC9101",
                    "doi": "10.1000/r611q.9101",
                    "title": "A",
                    "publication_date": "2026-09-15",
                    "publication_date_precision": "day",
                    "abstract": "a",
                }
            ],
            "europe_pmc_records": [],
            "fulltext_status_by_pmcid": {"PMC9101": {"fulltext_status": "UNKNOWN_STATUS", "artifact_id": None}},
        },
        {
            "new_pmids": ["9101"],
            "pubmed_articles": [
                {
                    "pmid": "9101",
                    "pmcid": "PMC9101",
                    "doi": "10.1000/r611q.9101",
                    "title": "A",
                    "publication_date": "2026-09-15",
                    "publication_date_precision": "day",
                    "abstract": "a",
                }
            ],
            "europe_pmc_records": [],
            "fulltext_status_by_pmcid": {
                "PMC9101": {"fulltext_status": "JATS_LICENCE_REJECTED", "artifact_id": "should-be-null"}
            },  # invalid status consistency
        },
    ]
    for case in bad_index_cases:
        with pytest.raises(api["R611QLiteratureParseError"], match="duplicate|pmid|pmcid|fulltext|status|unknown"):
            api["build_article_index_records"](
                new_pmids=case["new_pmids"],
                source_membership={"9101": ["litvar2"]} if "9101" in case["new_pmids"] else source_membership,
                pubmed_articles=case["pubmed_articles"],
                europe_pmc_records=case["europe_pmc_records"],
                fulltext_status_by_pmcid=case["fulltext_status_by_pmcid"],
            )

    with pytest.raises(api["R611QLiteratureParseError"], match="row|field|status|artifact"):
        api["to_article_index_jsonl"](
            [
                {
                    "schema": "raptor.external.r611q_literature_article.v1",
                    "pmid": "9101",
                    "discovery_sources": ["litvar2"],
                    "pubmed_status": "RESOLVED",
                    "pmcid": "PMC9101",
                    "doi": "10.1000/r611q.9101",
                    "title": "A",
                    "publication_date": "2026-09-15",
                    "publication_date_precision": "day",
                    "abstract": "a",
                    "europe_pmc_status": "RESOLVED",
                    "is_open_access": "Y",
                    "licence": "CC BY",
                    "fulltext_status": "ACQUIRED_CC_BY",
                    "fulltext_artifact_id": None,  # inconsistent
                }
            ]
        )


def test_ac10_bundle_manifest_self_hash_create_only_write_and_aggregate_only_summary(
    tmp_path: Path,
) -> None:
    api = _bundle_api()
    article_index_body = b'{"schema":"raptor.external.r611q_literature_article.v1","pmid":"9101"}\n'
    litvar_body = b'{"pmids":["9101"],"pmcids":["PMC9101"]}'
    fulltext_body = _jats_xml(
        pmcid="PMC9101",
        licence_text="Distributed under the Creative Commons Attribution License (CC BY 4.0).",
    ).encode("utf-8")

    artifacts = [
        _artifact_record(
            artifact_id="raw-litvar2-publications",
            source_id="litvar2_publications",
            relative_path="raw/litvar2-publications.json",
            body=litvar_body,
            role="RAW_RESPONSE",
        ),
        _artifact_record(
            artifact_id="normalized-article-index",
            source_id="article_index",
            relative_path="normalized/article-index.jsonl",
            body=article_index_body,
            role="ARTICLE_INDEX",
        ),
        _artifact_record(
            artifact_id="fulltext-PMC9101",
            source_id="fulltext",
            relative_path="fulltext/PMC9101.xml",
            body=fulltext_body,
            role="FULLTEXT_XML",
        ),
    ]
    sources = [
        _source_record(
            source_id="litvar2_publications",
            source_kind="litvar2_publications",
            artifact_ids=["raw-litvar2-publications"],
        ),
        _source_record(
            source_id="article_index",
            source_kind="article_index",
            artifact_ids=["normalized-article-index"],
        ),
        _source_record(
            source_id="fulltext",
            source_kind="fulltext",
            artifact_ids=["fulltext-PMC9101"],
        ),
    ]
    manifest = api["build_bundle_manifest"](
        bundle_id="r611q-literature-expansion-2026-09-15",
        created_at="2026-09-15T00:00:00Z",
        query={"gene": "TSC2", "variant": "R611Q"},
        artifacts=artifacts,
        sources=sources,
        truncation={},
        boundaries={"network": "operator-only", "external_output_only": True},
        counts={
            "litvar2_pmids": 3,
            "clinvar_pmids": 2,
            "litvar2_clinvar_intersection": 1,
            "discovery_union_pmids": 4,
            "baseline_union_overlap": 1,
            "new_pmid_leads": 3,
            "pubmed_records_returned": 2,
            "pubmed_records_unresolved": 1,
            "pubmed_abstracts": 1,
            "pubmed_pmcids": 1,
            "pubmed_dois": 2,
            "europe_pmc_records_returned": 2,
            "europe_pmc_abstracts": 1,
            "europe_pmc_pmcids": 1,
            "europe_pmc_open_access": 1,
            "licence_cc_by": 1,
            "licence_cc_by_nc_nd": 1,
            "licence_cc_by_nc_sa": 0,
            "licence_absent": 0,
            "fulltext_candidates": 1,
            "article_index_rows": 3,
        },
        unresolved={
            "pubmed_missing_pmids": ["9104"],
            "europe_pmc_unresolved_pmids": ["9103"],
        },
        licence_counts={"CC BY": 1, "CC BY-NC-ND": 1, "CC BY-NC-SA": 0, "ABSENT": 0},
    )
    assert manifest["bundle_id"] == "r611q-literature-expansion-2026-09-15"
    assert manifest["content_hash"] == api["compute_bundle_content_hash"](manifest)
    api["validate_manifest_hash"](manifest)

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    output_root = tmp_path / "external-root"
    output_root.mkdir()
    payloads = {
        "raw/litvar2-publications.json": litvar_body,
        "normalized/article-index.jsonl": article_index_body,
        "fulltext/PMC9101.xml": fulltext_body,
    }
    write_result = api["write_bundle_run"](
        repo_root=repo_root,
        output_root=output_root,
        run_name="r611q-literature-expansion-2026-09-15",
        manifest=manifest,
        artifact_payloads=payloads,
    )
    run_dir = output_root / "r611q-literature-expansion-2026-09-15"
    assert run_dir.exists()
    assert write_result["run_dir"] == run_dir
    manifest_path = run_dir / MANIFEST_FILENAME
    assert manifest_path.exists()

    with pytest.raises(api["BundleBoundaryError"]):
        api["write_bundle_run"](
            repo_root=repo_root,
            output_root=output_root,
            run_name="r611q-literature-expansion-2026-09-15",
            manifest=manifest,
            artifact_payloads=payloads,
        )

    summary = api["build_committed_summary"](manifest)
    _assert_aggregate_only_summary(summary)


def test_ac10_validate_manifest_hash_enforces_extension_contract_and_detects_mutations() -> None:
    api = _bundle_api()
    article_index_body = (
        b'{"schema":"raptor.external.r611q_literature_article.v1","pmid":"9101"}\n'
        b'{"schema":"raptor.external.r611q_literature_article.v1","pmid":"9102"}\n'
    )
    fulltext_body = _jats_xml(
        pmcid="PMC9101",
        licence_text="Distributed under the Creative Commons Attribution License (CC BY 4.0).",
    ).encode("utf-8")
    artifacts = [
        _artifact_record(
            artifact_id="normalized-article-index",
            source_id="article_index",
            relative_path="normalized/article-index.jsonl",
            body=article_index_body,
            role="ARTICLE_INDEX",
        ),
        _artifact_record(
            artifact_id="fulltext-PMC9101",
            source_id="fulltext",
            relative_path="fulltext/PMC9101.xml",
            body=fulltext_body,
            role="FULLTEXT_XML",
        ),
    ]
    sources = [
        _source_record(
            source_id="article_index",
            source_kind="article_index",
            artifact_ids=["normalized-article-index"],
        ),
        _source_record(
            source_id="fulltext",
            source_kind="fulltext",
            artifact_ids=["fulltext-PMC9101"],
        ),
    ]
    manifest = api["build_bundle_manifest"](
        bundle_id="r611q-literature-expansion-2026-09-15",
        created_at="2026-09-15T00:00:00Z",
        query={"gene": "TSC2", "variant": "R611Q"},
        artifacts=artifacts,
        sources=sources,
        truncation={},
        boundaries={"network": "operator-only", "external_output_only": True},
    )
    manifest.update(
        {
            "baseline_hashes": {"discovery_shelf_sources": "1" * 64},
            "source_response_hashes": {
                "litvar2_publications": "2" * 64,
                "clinvar_uid_search": "3" * 64,
                "clinvar_pubmed_links": "4" * 64,
                "pubmed_efetch": "5" * 64,
                "europe_pmc_core": "6" * 64,
            },
            "fulltext_artifact_hashes": ["7" * 64],
            "counts": {
                "sources": len(sources),
                "artifacts": len(artifacts),
                "litvar2_pmids": 5,
                "clinvar_pmids": 4,
                "litvar2_clinvar_intersection": 2,
                "discovery_union_pmids": 7,
                "baseline_union_overlap": 5,
                "new_pmid_leads": 2,
                "pubmed_records_returned": 1,
                "pubmed_records_unresolved": 1,
                "pubmed_abstracts": 1,
                "pubmed_pmcids": 1,
                "pubmed_dois": 1,
                "europe_pmc_records_returned": 1,
                "europe_pmc_abstracts": 1,
                "europe_pmc_pmcids": 1,
                "europe_pmc_open_access": 1,
                "licence_cc_by": 1,
                "licence_cc_by_nc_nd": 0,
                "licence_cc_by_nc_sa": 0,
                "licence_absent": 0,
                "fulltext_candidates": 1,
                "new_pmids": 2,
                "article_index_rows": 2,
                "fulltext_acquired": 1,
            },
            "unresolved": {
                "pubmed_missing_pmids": ["9104"],
                "europe_pmc_unresolved_pmids": ["9103"],
            },
        }
    )
    manifest["content_hash"] = api["compute_bundle_content_hash"](manifest)
    api["validate_manifest_hash"](manifest)

    mutation_cases = [
        ("arbitrary-extra-key", lambda m: m.__setitem__("unexpected_extra", True)),
        ("bool-count", lambda m: m["counts"].__setitem__("new_pmids", True)),
        ("count-drift", lambda m: m["counts"].__setitem__("sources", 999)),
        ("nested-identity-injection", lambda m: m["unresolved"].__setitem__("pubmed_missing_pmids", ["9104", "9104", "bad"])),
        ("unsorted-fulltext-hashes", lambda m: m.__setitem__("fulltext_artifact_hashes", ["f" * 64, "0" * 64])),
        ("acquired-count-drift", lambda m: m["counts"].__setitem__("fulltext_acquired", 2)),
        ("new-pmids-row-count-drift", lambda m: m["counts"].__setitem__("article_index_rows", 1)),
    ]
    for _name, mutate in mutation_cases:
        candidate = json.loads(json.dumps(manifest))
        mutate(candidate)
        candidate["content_hash"] = api["compute_bundle_content_hash"](candidate)
        with pytest.raises(Exception, match="schema|key|type|count|pmid|duplicate|unexpected|invalid"):
            api["validate_manifest_hash"](candidate)


def test_ac10_manifest_hash_binds_exact_raw_response_and_fulltext_artifact_hashes() -> None:
    api = _bundle_api()
    raw_litvar_body = b'{"pmids":[1,2],"pmcids":["PMC1"],"pmids_count":2}'
    raw_clinvar_body = b'{"esearchresult":{"idlist":["12397"]}}'
    fulltext_a_body = b"<article>A</article>"
    fulltext_b_body = b"<article>B</article>"

    artifacts = [
        _artifact_record(
            artifact_id="raw-litvar2-publications",
            source_id="litvar2_publications",
            relative_path="raw/litvar2-publications.json",
            body=raw_litvar_body,
            role="RAW_RESPONSE",
        ),
        _artifact_record(
            artifact_id="raw-clinvar-uid-search",
            source_id="clinvar_uid_search",
            relative_path="raw/clinvar-esearch.json",
            body=raw_clinvar_body,
            role="RAW_RESPONSE",
        ),
        _artifact_record(
            artifact_id="fulltext-PMC1001",
            source_id="fulltext",
            relative_path="fulltext/PMC1001.xml",
            body=fulltext_a_body,
            role="FULLTEXT_XML",
        ),
        _artifact_record(
            artifact_id="fulltext-PMC1002",
            source_id="fulltext",
            relative_path="fulltext/PMC1002.xml",
            body=fulltext_b_body,
            role="FULLTEXT_XML",
        ),
    ]
    sources = [
        _source_record(
            source_id="litvar2_publications",
            source_kind="litvar2_publications",
            artifact_ids=["raw-litvar2-publications"],
        ),
        _source_record(
            source_id="clinvar_uid_search",
            source_kind="clinvar_uid_search",
            artifact_ids=["raw-clinvar-uid-search"],
        ),
        _source_record(
            source_id="fulltext",
            source_kind="fulltext",
            artifact_ids=["fulltext-PMC1001", "fulltext-PMC1002"],
        ),
    ]
    manifest = api["build_bundle_manifest"](
        bundle_id="r611q-literature-expansion-2026-09-15",
        created_at="2026-09-15T00:00:00Z",
        query={"gene": "TSC2", "variant": "R611Q"},
        artifacts=artifacts,
        sources=sources,
        truncation={},
        boundaries={"network": "operator-only", "external_output_only": True},
        source_response_hashes={
            "litvar2_publications": "f" * 64,
            "unrelated": "e" * 64,
        },
        counts={"fulltext_candidates": 2},
    )
    expected_source_hashes = {
        artifact["source_id"]: artifact["sha256"]
        for artifact in artifacts
        if artifact["role"] == "RAW_RESPONSE"
    }
    expected_fulltext_hashes = sorted(
        [artifact["sha256"] for artifact in artifacts if artifact["role"] == "FULLTEXT_XML"]
    )
    assert manifest["source_response_hashes"] == expected_source_hashes
    assert manifest["fulltext_artifact_hashes"] == expected_fulltext_hashes
    api["validate_manifest_hash"](manifest)

    mutation_cases = [
        (
            "same-shape-replaced-digests",
            lambda m: m.__setitem__(
                "source_response_hashes",
                {key: ("a" * 64 if index == 0 else "b" * 64) for index, key in enumerate(m["source_response_hashes"])},
            ),
        ),
        (
            "extra-source-response-key",
            lambda m: m["source_response_hashes"].__setitem__("rogue", "c" * 64),
        ),
        (
            "missing-source-response-key",
            lambda m: m["source_response_hashes"].pop("clinvar_uid_search", None),
        ),
        (
            "same-shape-unrelated-fulltext-hashes",
            lambda m: m.__setitem__("fulltext_artifact_hashes", ["0" * 64, "1" * 64]),
        ),
    ]
    for _name, mutate in mutation_cases:
        candidate = json.loads(json.dumps(manifest))
        mutate(candidate)
        candidate["content_hash"] = api["compute_bundle_content_hash"](candidate)
        with pytest.raises(Exception, match="source_response_hashes|fulltext_artifact_hashes|derived|hash|invalid|key"):
            api["validate_manifest_hash"](candidate)


def test_ac10_build_committed_summary_coerces_unresolved_lists_to_counts_and_validates_first() -> None:
    api = _bundle_api()
    manifest = {
        "schema": "raptor.external.r611q_literature_bundle.v1",
        "bundle_id": "r611q-literature-expansion-2026-09-15",
        "created_at": "2026-09-15T00:00:00Z",
        "query": {"gene": "TSC2", "variant": "R611Q"},
        "artifacts": [],
        "sources": [],
        "counts": {
            "sources": 0,
            "artifacts": 0,
            "litvar2_pmids": 6,
            "clinvar_pmids": 5,
            "litvar2_clinvar_intersection": 2,
            "discovery_union_pmids": 9,
            "baseline_union_overlap": 6,
            "new_pmid_leads": 3,
            "pubmed_records_returned": 1,
            "pubmed_records_unresolved": 2,
            "pubmed_abstracts": 1,
            "pubmed_pmcids": 1,
            "pubmed_dois": 1,
            "europe_pmc_records_returned": 2,
            "europe_pmc_abstracts": 1,
            "europe_pmc_pmcids": 1,
            "europe_pmc_open_access": 1,
            "licence_cc_by": 1,
            "licence_cc_by_nc_nd": 1,
            "licence_cc_by_nc_sa": 0,
            "licence_absent": 0,
            "fulltext_candidates": 1,
            "fulltext_acquired": 1,
            "article_index_rows": 3,
            "new_pmids": 3,
        },
        "truncation": {},
        "boundaries": {"network": "operator-only", "external_output_only": True},
        "baseline_hashes": {"discovery_shelf_sources": "1" * 64},
        "source_response_hashes": {
            "litvar2_publications": "2" * 64,
            "clinvar_uid_search": "3" * 64,
            "clinvar_pubmed_links": "4" * 64,
            "pubmed_efetch": "5" * 64,
            "europe_pmc_core": "6" * 64,
        },
        "licence_counts": {"CC BY": 1, "CC BY-NC-ND": 1, "CC BY-NC-SA": 0, "ABSENT": 0},
        "unresolved": {
            "pubmed_missing_pmids": ["9103", "9104"],
            "europe_pmc_unresolved_pmids": ["9104"],
        },
        "fulltext_artifact_hashes": ["7" * 64],
    }
    manifest["content_hash"] = api["compute_bundle_content_hash"](manifest)
    summary = api["build_committed_summary"](manifest)
    _assert_aggregate_only_summary(summary)
    assert summary["unresolved_counts"] == {
        "pubmed_missing_pmids": 2,
        "europe_pmc_unresolved_pmids": 1,
    }

    arithmetic_mutations = [
        lambda s: s["counts"].__setitem__("discovery_union_pmids", s["counts"]["discovery_union_pmids"] + 1),
        lambda s: s["counts"].__setitem__("pubmed_records_unresolved", s["counts"]["pubmed_records_unresolved"] + 1),
        lambda s: s["counts"].__setitem__("europe_pmc_records_returned", s["counts"]["europe_pmc_records_returned"] + 1),
        lambda s: s["counts"].__setitem__("licence_absent", s["counts"]["licence_absent"] + 1),
        lambda s: s["counts"].__setitem__("fulltext_candidates", s["counts"]["licence_cc_by"] + 1),
        lambda s: s["counts"].__setitem__("article_index_rows", s["counts"]["new_pmid_leads"] + 1),
    ]
    for mutate in arithmetic_mutations:
        candidate = json.loads(json.dumps(summary))
        mutate(candidate)
        with pytest.raises(AssertionError):
            _assert_aggregate_only_summary(candidate)

    bad_manifest = dict(manifest)
    bad_manifest["arbitrary_key"] = "should-fail"
    bad_manifest["content_hash"] = api["compute_bundle_content_hash"](bad_manifest)
    with pytest.raises(Exception, match="schema|key|validation|unexpected|invalid"):
        api["build_committed_summary"](bad_manifest)


def test_ac11_static_package_boundaries_no_network_imports_and_no_forbidden_domain_crossings() -> None:
    if not PACKAGE_ROOT.exists():
        pytest.fail(f"R611Q literature package is not implemented: {PACKAGE_ROOT}")
    if not OPERATOR_SCRIPT.is_file():
        pytest.fail(f"R611Q literature operator script is not implemented: {OPERATOR_SCRIPT}")

    forbidden: list[str] = []
    network_forbidden: list[str] = []

    package_targets = _iter_python_files(PACKAGE_ROOT)
    for path in package_targets:
        for imported, lineno in _module_imports(path):
            if any(imported == blocked or imported.startswith(blocked + ".") for blocked in FORBIDDEN_IMPORT_PREFIXES):
                forbidden.append(f"{path.relative_to(REPO_ROOT)}:{lineno}:{imported}")
            if any(
                imported == blocked or imported.startswith(blocked + ".")
                for blocked in PACKAGE_FORBIDDEN_NETWORK_IMPORTS
            ):
                network_forbidden.append(f"{path.relative_to(REPO_ROOT)}:{lineno}:{imported}")

    for imported, lineno in _module_imports(OPERATOR_SCRIPT):
        if any(imported == blocked or imported.startswith(blocked + ".") for blocked in FORBIDDEN_IMPORT_PREFIXES):
            forbidden.append(f"{OPERATOR_SCRIPT.relative_to(REPO_ROOT)}:{lineno}:{imported}")

    assert not network_forbidden, "network-capable modules must not be imported in package modules:\n" + "\n".join(
        network_forbidden
    )
    assert not forbidden, "forbidden import boundary crossings:\n" + "\n".join(forbidden)


def test_ac12_operator_cli_exposes_dry_run_baseline_pin_and_dry_run_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_operator_module()
    parser = _symbol(module, "build_arg_parser")()

    dry_output_root = tmp_path / "dry-run-root"
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text("{}", encoding="utf-8")
    config_path = tmp_path / "r611q-config.yaml"
    config_path.write_text(yaml.safe_dump(_minimal_operator_config(), sort_keys=False), encoding="utf-8")

    args = parser.parse_args(
        [
            "--config",
            str(config_path),
            "--output-root",
            str(dry_output_root),
            "--baseline-manifest",
            str(baseline_path),
            "--dry-run",
            "--min-ncbi-interval-seconds",
            "0.34",
        ]
    )
    assert args.dry_run is True
    assert Path(args.output_root) == dry_output_root
    assert Path(args.baseline_manifest) == baseline_path
    assert float(args.min_ncbi_interval_seconds) == 0.34

    if hasattr(module, "run_ingestion"):
        monkeypatch.setattr(
            module,
            "run_ingestion",
            lambda **_kwargs: (_ for _ in ()).throw(AssertionError("dry-run must not run ingestion")),
        )
    if hasattr(module, "_make_transport"):
        monkeypatch.setattr(
            module,
            "_make_transport",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("dry-run must not build transport")),
        )

    rc = _symbol(module, "main")(
        [
            "--config",
            str(config_path),
            "--output-root",
            str(dry_output_root),
            "--baseline-manifest",
            str(baseline_path),
            "--dry-run",
        ]
    )
    assert rc == 0
    if dry_output_root.exists():
        assert not any(dry_output_root.rglob("*")), "dry-run must write nothing"


def test_ac12_operator_probe_reference_structure_validation_and_drift_tolerance_contract() -> None:
    source_text = _operator_source_text()
    module = _load_operator_module()

    validate_probe_reference_counts = _symbol(module, "_validate_probe_reference_counts")
    validate_probe_reference_counts(
        observed={"a": 1, "b": 0},
        expected={"a": 1, "b": 0},
    )
    invalid_cases = [
        ({"a": 1}, {"a": 1, "b": 0}),  # missing key
        ({"a": 1, "b": 0, "c": 1}, {"a": 1, "b": 0}),  # extra key
        ({"a": True, "b": 0}, {"a": 1, "b": 0}),  # bool != int
        ({"a": 1.0, "b": 0}, {"a": 1, "b": 0}),  # float != int
        ({"a": 1, "b": 0}, {"a": True, "b": 0}),  # bool expected invalid
        ({"a": 1, "b": 0}, {"a": 1.0, "b": 0}),  # float expected invalid
    ]
    for observed, expected in invalid_cases:
        with pytest.raises(Exception, match="key|type|count|expected|observed|mismatch"):
            validate_probe_reference_counts(observed=observed, expected=expected)

    for observed, expected in (
        ({"a": 2, "b": 0}, {"a": 1, "b": 0}),
        ({"a": 1, "b": 3}, {"a": 1, "b": 0}),
    ):
        validate_probe_reference_counts(observed=observed, expected=expected)

    assert "probe_reference_counts" in source_text
    assert "_validate_probe_reference_counts(" in source_text
    assert "probe_expected_counts" not in source_text
    assert "_validate_expected_counts(" not in source_text
    assert re.search(
        r"_validate_probe_reference_counts\([^)]*probe_reference_counts",
        source_text,
        flags=re.DOTALL,
    ) is not None
    validate_idx = source_text.find("_validate_probe_reference_counts(")
    for publication_step in ("build_bundle_manifest(", "write_bundle_run("):
        step_idx = source_text.find(publication_step)
        if step_idx != -1:
            assert validate_idx != -1
            assert validate_idx < step_idx, (
                f"expected-probe validation must run before publication step {publication_step}"
            )

    assert "artifact_payloads" in source_text
    assert "fulltext/" in source_text or "fulltext" in source_text
    assert re.search(r"artifact_payloads\[[^\]]+\]\s*=", source_text) is not None
    assert re.search(r"for\s+.*fulltext.*:\s*\n\s+pass\b", source_text, flags=re.IGNORECASE) is None


def test_ac12_operator_count_drift_is_diagnostic_and_allows_bundle_and_summary_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_operator_module()
    config = _minimal_operator_config()
    config["probe_reference_counts"] = {key: 0 for key in PROBE_COUNT_AXES}
    config["committed_summary_path"] = f"data/census/{tmp_path.name}-probe-drift-summary.json"
    config_path = tmp_path / "r611q-config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text("{}", encoding="utf-8")
    summary_path = (REPO_ROOT / config["committed_summary_path"]).resolve()
    if summary_path.exists():
        summary_path.unlink()

    monkeypatch.setattr(
        module,
        "_validate_plan",
        lambda _cfg: {
            "litvar_url": "https://example.org/litvar",
            "esearch_url": "https://example.org/esearch",
            "elink_url": "https://example.org/elink",
            "tool": "raptor",
            "clinvar_uid": "12397",
        },
    )
    monkeypatch.setattr(module, "_load_baseline_bytes", lambda _path: b"{}")
    monkeypatch.setattr(module, "_make_transport", lambda _rate_limiter: (lambda _url: {}))
    monkeypatch.setattr(
        module.parse_mod,
        "parse_baseline_manifest",
        lambda **_kwargs: {"pmid_publications": [], "raw_sha256": "1" * 64},
    )
    monkeypatch.setattr(
        module.parse_mod,
        "parse_litvar_publications",
        lambda _payload: {"pmids": ["9101"], "pmcids": [], "pmid_count": 1, "pmcid_count": 0},
    )
    monkeypatch.setattr(module.parse_mod, "parse_clinvar_uid_esearch", lambda _payload, *, expected_uid: expected_uid)
    monkeypatch.setattr(module.parse_mod, "parse_clinvar_pubmed_links", lambda _payload, *, expected_uid: [])
    monkeypatch.setattr(
        module.parse_mod,
        "derive_discovery_membership",
        lambda **_kwargs: {
            "litvar2_pmids": 1,
            "clinvar_pmids": 0,
            "intersection_pmids": 0,
            "union_pmids": 1,
            "new_pmids": ["9101"],
            "source_membership": {"9101": ["litvar2"]},
        },
    )
    monkeypatch.setattr(
        module.endpoint_mod,
        "build_pubmed_efetch_url",
        lambda *, pmids, tool: f"https://example.org/efetch?tool={tool}&id={','.join(pmids)}",
    )
    monkeypatch.setattr(
        module.endpoint_mod,
        "build_europe_pmc_core_url",
        lambda *, pmids, page_size: f"https://example.org/core?pageSize={page_size}&ids={','.join(pmids)}",
    )
    monkeypatch.setattr(
        module.endpoint_mod,
        "request_with_transport",
        lambda *, requested_url, transport: {
            "requested_url": requested_url,
            "final_url": requested_url,
            "http_status": 200,
            "media_type": "application/json",
            "body": b"{}",
            "byte_length": 2,
            "sha256": _sha256_bytes(b"{}"),
        },
    )
    monkeypatch.setattr(
        module.parse_mod,
        "parse_pubmed_articles_xml",
        lambda _xml, *, expected_pmids: {
            "articles": [
                {
                    "pmid": expected_pmids[0],
                    "pmcid": None,
                    "doi": "10.1000/r611q-drift",
                    "title": "R611Q drift sentinel",
                    "publication_date": "2026-01-01",
                    "publication_date_precision": "day",
                    "abstract": None,
                }
            ],
            "requested_but_missing_pmids": [],
        },
    )
    monkeypatch.setattr(
        module.parse_mod,
        "parse_europe_pmc_core",
        lambda _payload, *, requested_pmids: {
            "records": [
                {
                    "pmid": requested_pmids[0],
                    "pmcid": None,
                    "doi": "10.1000/r611q-drift",
                    "title": "R611Q drift sentinel",
                    "abstract": "Europe PMC abstract present despite zero planning reference.",
                    "is_open_access": "N",
                    "licence": None,
                }
            ],
            "requested_but_unresolved_pmids": [],
            "counts": {"records_returned": 1, "pmcid_count": 0, "abstract_count": 1},
        },
    )
    monkeypatch.setattr(module.parse_mod, "select_cc_by_fulltext_candidates", lambda _records: [])
    monkeypatch.setattr(
        module.parse_mod,
        "build_article_index_records",
        lambda **_kwargs: [
            {
                "schema": "raptor.external.r611q_literature_article.v1",
                "pmid": "9101",
                "discovery_sources": ["litvar2"],
                "pubmed_status": "RESOLVED",
                "pmcid": None,
                "doi": "10.1000/r611q-drift",
                "title": "R611Q drift sentinel",
                "publication_date": "2026-01-01",
                "publication_date_precision": "day",
                "abstract": None,
                "europe_pmc_status": "RESOLVED",
                "is_open_access": "N",
                "licence": None,
                "fulltext_status": "NOT_ELIGIBLE",
                "fulltext_artifact_id": None,
            }
        ],
    )
    monkeypatch.setattr(module.parse_mod, "to_article_index_jsonl", lambda rows: "\n".join(json.dumps(row) for row in rows))

    publication_calls: list[str] = []
    captured_manifest: dict[str, Any] = {}

    def fake_build_bundle_manifest(**kwargs):
        counts = dict(kwargs["counts"])
        counts["sources"] = len(kwargs["sources"])
        counts["artifacts"] = len(kwargs["artifacts"])
        counts["fulltext_acquired"] = 0
        manifest = {
            "bundle_id": kwargs["bundle_id"],
            "counts": counts,
            "content_hash": "f" * 64,
        }
        captured_manifest.clear()
        captured_manifest.update(manifest)
        return manifest

    monkeypatch.setattr(module.bundle_mod, "build_bundle_manifest", fake_build_bundle_manifest)

    def fake_write_bundle_run(**_kwargs):
        publication_calls.append("bundle")
        return {"run_dir": tmp_path / "run", "manifest_path": tmp_path / "run" / MANIFEST_FILENAME}

    monkeypatch.setattr(module.bundle_mod, "write_bundle_run", fake_write_bundle_run)

    def fake_build_committed_summary(_manifest):
        publication_calls.append("summary")
        return {"schema": "test.summary"}

    monkeypatch.setattr(module.bundle_mod, "build_committed_summary", fake_build_committed_summary)

    class _MemoryWriter:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def write(self, _payload: bytes) -> int:
            return 0

    monkeypatch.setattr(module, "open", lambda *_args, **_kwargs: _MemoryWriter(), raising=False)

    rc = module.main(
        [
            "--config",
            str(config_path),
            "--baseline-manifest",
            str(baseline_path),
            "--summary-output",
            str(summary_path),
        ]
    )
    assert rc == 0
    assert publication_calls == ["bundle", "summary"]
    assert captured_manifest["counts"]["europe_pmc_abstracts"] == 1
    assert config["probe_reference_counts"]["europe_pmc_abstracts"] == 0
    assert (
        captured_manifest["counts"]["europe_pmc_abstracts"]
        > config["probe_reference_counts"]["europe_pmc_abstracts"]
    )
    assert not summary_path.exists()


def test_ac12_operator_pubmed_slice_is_single_batch_and_raw_pubmed_urls_are_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_operator_module()
    config = _minimal_operator_config()
    config["probe_expected_counts"] = {key: 0 for key in PROBE_COUNT_AXES}
    config["sources"]["pubmed"]["batch_size"] = 3
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        module,
        "_validate_plan",
        lambda _cfg: {
            "litvar_url": "https://example.org/litvar",
            "esearch_url": "https://example.org/esearch",
            "elink_url": "https://example.org/elink",
            "tool": "raptor",
            "clinvar_uid": "12397",
        },
    )
    monkeypatch.setattr(module, "_load_baseline_bytes", lambda _path: b"{}")
    monkeypatch.setattr(
        module.parse_mod,
        "parse_baseline_manifest",
        lambda **_kwargs: {"pmid_publications": [], "raw_sha256": "1" * 64},
    )
    monkeypatch.setattr(
        module.parse_mod,
        "parse_litvar_publications",
        lambda _payload: {"pmids": ["9101", "9102", "9103"], "pmcids": [], "pmid_count": 3, "pmcid_count": 0},
    )
    monkeypatch.setattr(module.parse_mod, "parse_clinvar_uid_esearch", lambda _payload, *, expected_uid: expected_uid)
    monkeypatch.setattr(module.parse_mod, "parse_clinvar_pubmed_links", lambda _payload, *, expected_uid: ["9102"])
    monkeypatch.setattr(
        module.parse_mod,
        "derive_discovery_membership",
        lambda **_kwargs: {
            "litvar2_pmids": 3,
            "clinvar_pmids": 1,
            "intersection_pmids": 1,
            "union_pmids": 3,
            "new_pmids": ["9101", "9102", "9103"],
            "source_membership": {"9101": ["litvar2"], "9102": ["litvar2", "clinvar"], "9103": ["litvar2"]},
        },
    )
    monkeypatch.setattr(
        module.parse_mod,
        "parse_pubmed_articles_xml",
        lambda _xml, *, expected_pmids: {
            "articles": [
                {
                    "pmid": expected_pmids[0],
                    "pmcid": "PMC9101",
                    "doi": "10.1000/a",
                    "title": "A",
                    "publication_date": "2026-01-01",
                    "publication_date_precision": "day",
                    "abstract": "a",
                }
            ],
            "requested_but_missing_pmids": expected_pmids[1:],
        },
    )
    monkeypatch.setattr(
        module.parse_mod,
        "parse_europe_pmc_core",
        lambda _payload, *, requested_pmids: {
            "records": [],
            "requested_but_unresolved_pmids": list(requested_pmids),
            "counts": {"records_returned": 0, "pmcid_count": 0, "abstract_count": 0},
        },
    )
    monkeypatch.setattr(module.parse_mod, "select_cc_by_fulltext_candidates", lambda _records: [])
    monkeypatch.setattr(
        module.parse_mod,
        "build_article_index_records",
        lambda **_kwargs: [
            {
                "schema": "raptor.external.r611q_literature_article.v1",
                "pmid": "9101",
                "discovery_sources": ["litvar2"],
                "pubmed_status": "RESOLVED",
                "pmcid": "PMC9101",
                "doi": "10.1000/a",
                "title": "A",
                "publication_date": "2026-01-01",
                "publication_date_precision": "day",
                "abstract": "a",
                "europe_pmc_status": "UNRESOLVED",
                "is_open_access": "N",
                "licence": None,
                "fulltext_status": "NOT_ELIGIBLE",
                "fulltext_artifact_id": None,
            },
            {
                "schema": "raptor.external.r611q_literature_article.v1",
                "pmid": "9102",
                "discovery_sources": ["litvar2", "clinvar"],
                "pubmed_status": "UNRESOLVED",
                "pmcid": None,
                "doi": None,
                "title": None,
                "publication_date": None,
                "publication_date_precision": None,
                "abstract": None,
                "europe_pmc_status": "UNRESOLVED",
                "is_open_access": "N",
                "licence": None,
                "fulltext_status": "NOT_ELIGIBLE",
                "fulltext_artifact_id": None,
            },
            {
                "schema": "raptor.external.r611q_literature_article.v1",
                "pmid": "9103",
                "discovery_sources": ["litvar2"],
                "pubmed_status": "UNRESOLVED",
                "pmcid": None,
                "doi": None,
                "title": None,
                "publication_date": None,
                "publication_date_precision": None,
                "abstract": None,
                "europe_pmc_status": "UNRESOLVED",
                "is_open_access": "N",
                "licence": None,
                "fulltext_status": "NOT_ELIGIBLE",
                "fulltext_artifact_id": None,
            },
        ],
    )
    monkeypatch.setattr(module.parse_mod, "to_article_index_jsonl", lambda rows: "\n".join(json.dumps(row) for row in rows))
    monkeypatch.setattr(module, "_validate_expected_counts", lambda **_kwargs: None)

    efetch_urls: list[str] = []

    def fake_build_pubmed_efetch_url(*, pmids: list[str], tool: str) -> str:
        url = (
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
            f"?db=pubmed&retmode=xml&tool={tool}&id={','.join(pmids)}"
        )
        efetch_urls.append(url)
        return url

    monkeypatch.setattr(module.endpoint_mod, "build_pubmed_efetch_url", fake_build_pubmed_efetch_url)

    def fake_request_with_transport(*, requested_url: str, transport):
        body = b"{}"
        return {
            "requested_url": requested_url,
            "final_url": requested_url,
            "http_status": 200,
            "media_type": "application/json",
            "body": body,
            "byte_length": len(body),
            "sha256": _sha256_bytes(body),
        }

    monkeypatch.setattr(module.endpoint_mod, "request_with_transport", fake_request_with_transport)

    captured: dict[str, Any] = {}

    def fake_build_bundle_manifest(**kwargs):
        captured.update(kwargs)
        return {
            "bundle_id": kwargs["bundle_id"],
            "counts": {"sources": len(kwargs["sources"]), "artifacts": len(kwargs["artifacts"])},
            "content_hash": "f" * 64,
        }

    monkeypatch.setattr(module.bundle_mod, "build_bundle_manifest", fake_build_bundle_manifest)

    result = module.run_ingestion(
        config=config,
        baseline_manifest_path=baseline_path,
        transport=lambda _url: {},
    )
    assert result["manifest"]["content_hash"] == "f" * 64
    assert len(efetch_urls) == 1
    assert "batched" not in efetch_urls[0]
    pubmed_artifacts = [a for a in captured["artifacts"] if a["source_id"] == "pubmed"]
    assert len(pubmed_artifacts) == 1
    assert pubmed_artifacts[0]["requested_url"] == efetch_urls[0]
    assert pubmed_artifacts[0]["final_url"] == efetch_urls[0]
    assert pubmed_artifacts[0]["requested_url"] != "batched"
    assert pubmed_artifacts[0]["final_url"] != "batched"


def test_ac12_operator_pubmed_slice_rejects_multi_batch_need(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_operator_module()
    config = _minimal_operator_config()
    config["probe_expected_counts"] = {key: 0 for key in PROBE_COUNT_AXES}
    config["sources"]["pubmed"]["batch_size"] = 2
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        module,
        "_validate_plan",
        lambda _cfg: {
            "litvar_url": "https://example.org/litvar",
            "esearch_url": "https://example.org/esearch",
            "elink_url": "https://example.org/elink",
            "tool": "raptor",
            "clinvar_uid": "12397",
        },
    )
    monkeypatch.setattr(module, "_load_baseline_bytes", lambda _path: b"{}")
    monkeypatch.setattr(
        module.parse_mod,
        "parse_baseline_manifest",
        lambda **_kwargs: {"pmid_publications": [], "raw_sha256": "1" * 64},
    )
    monkeypatch.setattr(
        module.parse_mod,
        "parse_litvar_publications",
        lambda _payload: {"pmids": ["9101", "9102", "9103"], "pmcids": [], "pmid_count": 3, "pmcid_count": 0},
    )
    monkeypatch.setattr(module.parse_mod, "parse_clinvar_uid_esearch", lambda _payload, *, expected_uid: expected_uid)
    monkeypatch.setattr(module.parse_mod, "parse_clinvar_pubmed_links", lambda _payload, *, expected_uid: [])
    monkeypatch.setattr(
        module.parse_mod,
        "derive_discovery_membership",
        lambda **_kwargs: {
            "litvar2_pmids": 3,
            "clinvar_pmids": 0,
            "intersection_pmids": 0,
            "union_pmids": 3,
            "new_pmids": ["9101", "9102", "9103"],
            "source_membership": {"9101": ["litvar2"], "9102": ["litvar2"], "9103": ["litvar2"]},
        },
    )
    monkeypatch.setattr(module, "_validate_expected_counts", lambda **_kwargs: None)
    monkeypatch.setattr(
        module.endpoint_mod,
        "request_with_transport",
        lambda **_kwargs: {
            "requested_url": "https://example.org/x",
            "final_url": "https://example.org/x",
            "http_status": 200,
            "media_type": "application/json",
            "body": b"{}",
            "byte_length": 2,
            "sha256": _sha256_bytes(b"{}"),
        },
    )
    monkeypatch.setattr(
        module.parse_mod,
        "parse_pubmed_articles_xml",
        lambda _xml, *, expected_pmids: {"articles": [], "requested_but_missing_pmids": expected_pmids},
    )
    monkeypatch.setattr(
        module.parse_mod,
        "parse_europe_pmc_core",
        lambda _payload, *, requested_pmids: {"records": [], "requested_but_unresolved_pmids": requested_pmids, "counts": {"records_returned": 0, "pmcid_count": 0, "abstract_count": 0}},
    )
    monkeypatch.setattr(module.parse_mod, "select_cc_by_fulltext_candidates", lambda _records: [])
    monkeypatch.setattr(module.parse_mod, "build_article_index_records", lambda **_kwargs: [])
    monkeypatch.setattr(module.parse_mod, "to_article_index_jsonl", lambda _rows: "")
    monkeypatch.setattr(
        module.bundle_mod,
        "build_bundle_manifest",
        lambda **_kwargs: {"bundle_id": "x", "counts": {"sources": 0, "artifacts": 0}, "content_hash": "f" * 64},
    )

    with pytest.raises(module.R611QOperatorError, match="batch|bounded|single|slice|batch_size|new pmid"):
        module.run_ingestion(
            config=config,
            baseline_manifest_path=baseline_path,
            transport=lambda _url: {},
        )


def test_ac12_operator_rate_floor_rejects_invalid_values_before_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_operator_module()
    config = _minimal_operator_config()
    config_path = tmp_path / "r611q-config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        module,
        "_validate_plan",
        lambda _cfg: {
            "litvar_url": "https://example.org/litvar",
            "esearch_url": "https://example.org/esearch",
            "elink_url": "https://example.org/elink",
            "tool": "raptor",
            "clinvar_uid": "12397",
        },
    )
    monkeypatch.setattr(
        module,
        "run_ingestion",
        lambda **_kwargs: {"manifest": {"counts": {"sources": 0, "artifacts": 0}, "content_hash": "f" * 64}, "artifact_payloads": {}},
    )
    monkeypatch.setattr(
        module.bundle_mod,
        "write_bundle_run",
        lambda **_kwargs: {"run_dir": tmp_path / "run", "manifest_path": tmp_path / "run" / "bundle_manifest.json"},
    )

    transport_calls: list[float] = []

    def fake_make_transport(rate_limiter):
        transport_calls.append(float(getattr(rate_limiter, "_min_interval_by_host", {"x": -1}).get("eutils.ncbi.nlm.nih.gov", -1)))
        return lambda _url: {}

    monkeypatch.setattr(module, "_make_transport", fake_make_transport)

    for bad in ("0", "-0.01", "nan", "inf"):
        transport_calls.clear()
        rc = module.main(
            [
                "--config",
                str(config_path),
                "--baseline-manifest",
                str(baseline_path),
                "--min-ncbi-interval-seconds",
                bad,
            ]
        )
        assert rc == 1
        assert transport_calls == []

    rc = module.main(
        [
            "--config",
            str(config_path),
            "--baseline-manifest",
            str(baseline_path),
            "--min-ncbi-interval-seconds",
            "0.5",
        ]
    )
    assert rc == 0
    assert len(transport_calls) == 1
    assert transport_calls[0] >= 0.5


def test_ac12_operator_summary_output_contract_and_publication_order_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_text = _operator_source_text()
    assert "--summary-output" in source_text
    assert "committed_summary_path" in source_text
    assert "build_committed_summary(" in source_text
    assert "write_bundle_run(" in source_text
    assert "parse_cc_by_jats_fulltext(" in source_text
    assert "except parse_mod.JatsLicenceRejectedError" in source_text
    assert "except parse_mod.R611QLiteratureParseError:" not in source_text
    assert ".resolve()" in source_text
    assert "relative_to(REPO_ROOT" in source_text or "is_relative_to(REPO_ROOT" in source_text
    assert ".exists()" in source_text

    main_start = source_text.find("def main(")
    assert main_start != -1
    main_text = source_text[main_start:]
    write_idx = main_text.find("write_bundle_run(")
    build_summary_idx = main_text.find("build_committed_summary(")
    summary_write_idx = main_text.find("summary_output")
    assert write_idx != -1 and build_summary_idx != -1 and summary_write_idx != -1
    assert write_idx < build_summary_idx < summary_write_idx

    module = _load_operator_module()
    parser = _symbol(module, "build_arg_parser")()
    cfg = _minimal_operator_config()
    cfg["committed_summary_path"] = "data/census/r611q_literature_expansion_2026-09-15.json"
    config_path = tmp_path / "r611q-config.yaml"
    config_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text("{}", encoding="utf-8")

    explicit_summary_path = (REPO_ROOT / cfg["committed_summary_path"]).resolve()
    if explicit_summary_path.exists():
        pytest.fail(
            "test requires a non-existing summary path for create-only validation: "
            f"{explicit_summary_path}"
        )

    args = parser.parse_args(
        [
            "--config",
            str(config_path),
            "--baseline-manifest",
            str(baseline_path),
            "--dry-run",
            "--summary-output",
            str(explicit_summary_path),
        ]
    )
    assert Path(args.summary_output).resolve() == explicit_summary_path

    rc = _symbol(module, "main")(
        [
            "--config",
            str(config_path),
            "--baseline-manifest",
            str(baseline_path),
            "--dry-run",
            "--summary-output",
            str(explicit_summary_path),
        ]
    )
    assert rc == 0
    assert not explicit_summary_path.exists(), "dry-run must not create summary output"

    outside_path = (tmp_path / "outside-summary.json").resolve()
    preexisting_inside = explicit_summary_path
    preexisting_inside.parent.mkdir(parents=True, exist_ok=True)
    preexisting_inside.write_text("{}", encoding="utf-8")
    try:
        assert _symbol(module, "main")(
            [
                "--config",
                str(config_path),
                "--baseline-manifest",
                str(baseline_path),
                "--summary-output",
                str(outside_path),
            ]
        ) == 1
        assert _symbol(module, "main")(
            [
                "--config",
                str(config_path),
                "--baseline-manifest",
                str(baseline_path),
                "--summary-output",
                str(preexisting_inside),
            ]
        ) == 1
    finally:
        if preexisting_inside.exists():
            preexisting_inside.unlink()

    assert not explicit_summary_path.exists()

    def fake_run_ingestion(**_kwargs):
        return {
            "manifest": {
                "counts": {"sources": 2, "artifacts": 3},
                "content_hash": "f" * 64,
            },
            "artifact_payloads": {},
        }

    monkeypatch.setattr(module, "run_ingestion", fake_run_ingestion)
    monkeypatch.setattr(
        module.bundle_mod,
        "write_bundle_run",
        lambda **_kwargs: {"run_dir": tmp_path / "external-run", "manifest_path": tmp_path / "m.json"},
    )
    monkeypatch.setattr(
        module.bundle_mod,
        "build_committed_summary",
        lambda _manifest: {
            "schema": "raptor.external.r611q_literature_committed_summary.v1",
            "bundle_id": cfg["bundle_id"],
            "manifest_content_hash": "f" * 64,
            "baseline_hashes": {"baseline_manifest": "1" * 64},
            "source_response_hashes": {"litvar2_publications": "2" * 64},
            "counts": {"sources": 2, "artifacts": 3},
            "licence_counts": {},
            "unresolved_counts": {"pubmed_missing_pmids": 0, "europe_pmc_unresolved_pmids": 0},
            "boundaries": {"network": "operator-only", "external_output_only": True},
            "fulltext_artifact_hashes": [],
        },
    )

    def fail_open(*_args, **_kwargs):
        raise OSError("simulated summary write race")

    monkeypatch.setattr(module, "open", fail_open, raising=False)
    rc = _symbol(module, "main")(
        [
            "--config",
            str(config_path),
            "--baseline-manifest",
            str(baseline_path),
            "--summary-output",
            str(explicit_summary_path),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    assert "error:" in captured.err.lower()
    assert "failed to write committed summary" in captured.err.lower()
    assert "traceback" not in captured.err.lower()


def test_ac13_config_matches_v1_spec_endpoints_expected_counts_and_output_names() -> None:
    if not SPEC_PATH.is_file():
        pytest.fail(f"spec file not found: {SPEC_PATH}")
    if not CONFIG_PATH.is_file():
        pytest.fail(f"config file not found: {CONFIG_PATH}")

    spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    assert isinstance(spec, dict)
    assert isinstance(config, dict)

    assert config["schema"] == "raptor.external.r611q_literature_expansion_config.v1"
    assert config["config_version"] == "1.0.1"
    assert config["bundle_id"] == spec["output"]["external_bundle"]["bundle_id"]
    assert config["run_name"] == spec["output"]["external_bundle"]["run_name"]
    assert (
        config["output"]["environment_variable"]
        == spec["output"]["external_bundle"]["environment_variable"]
    )

    for source_key in (
        "litvar2_publications",
        "clinvar_uid_search",
        "clinvar_pubmed_links",
        "pubmed",
        "europe_pmc",
    ):
        assert config["sources"][source_key]["endpoint"] == spec["sources"][source_key]["endpoint"]

    assert (
        config["sources"]["fulltext"]["endpoint_template"]
        == spec["sources"]["fulltext"]["endpoint_template"]
    )
    assert (
        config["sources"]["fulltext"]["allowed_metadata_licences"]
        == spec["sources"]["fulltext"]["allowed_metadata_licences"]
    )
    assert (
        config["sources"]["fulltext"]["required_jats_licence"]
        == spec["sources"]["fulltext"]["required_jats_licence"]
    )
    assert config["probe_expected_counts"] == spec["probe_observation"]["counts"]
    assert (
        config["article_index"]["exact_fields"]
        == spec["article_index"]["exact_fields"]
    )


def test_ac14_committed_summary_pilot_file_is_present_and_aggregate_only() -> None:
    # Intentionally RED until the real pilot summary artifact is produced.
    assert SUMMARY_PATH.is_file(), (
        f"committed summary is required by spec and intentionally RED until pilot: {SUMMARY_PATH}"
    )
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    _assert_aggregate_only_summary(summary)
    spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    expected_probe_counts = spec["probe_observation"]["counts"]
    for key, expected_value in expected_probe_counts.items():
        assert summary["counts"][key] == expected_value
