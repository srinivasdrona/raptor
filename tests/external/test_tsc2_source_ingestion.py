from __future__ import annotations

import ast
import gzip
import hashlib
import json
import socket
from importlib import import_module
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "raptor"
PACKAGE_ROOT = SRC_ROOT / "external" / "tsc2_sources"
OPERATOR_SCRIPT = REPO_ROOT / "scripts" / "fetch_tsc2_source_bundle.py"
MANIFEST_FILENAME = "bundle_manifest.json"

FORBIDDEN_IMPORT_PREFIXES = (
    "raptor.scorer",
    "raptor.eval",
    "raptor.packet",
    "raptor.census",
    "raptor.kb",
    "raptor.rescuescreen",
)

FORBIDDEN_STATUS_TOKENS = (
    "classification",
    "pathogenic",
    "benign",
    "ps3",
    "bs3",
    "validated mechanism",
    "accepted claim",
    "acmg",
)

RETIRED_PMC_OA_ENDPOINT_PATH = "pmc/utils/oa/oa.fcgi"
REQUIRED_PILOT_SOURCE_IDS = [
    "pubmed",
    "litvar2",
    "pmc",
    "mavedb_clipe",
    "igvf_vamp_seq",
    "igvf_sge",
]


def _load_module(module_name: str):
    try:
        return import_module(module_name)
    except ImportError as exc:
        pytest.fail(f"TSC2 source ingestion module {module_name!r} is not implemented: {exc}")


def _symbol(module: Any, symbol_name: str):
    if not hasattr(module, symbol_name):
        pytest.fail(
            f"TSC2 source ingestion module {module.__name__!r} is missing public "
            f"symbol {symbol_name!r}"
        )
    return getattr(module, symbol_name)


def _endpoint_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_sources.endpoint")
    return {
        "EndpointSecurityError": _symbol(module, "EndpointSecurityError"),
        "build_pubmed_esearch_url": _symbol(module, "build_pubmed_esearch_url"),
        "build_pubmed_efetch_url": _symbol(module, "build_pubmed_efetch_url"),
        "build_litvar2_gene_url": _symbol(module, "build_litvar2_gene_url"),
        "assert_allowed_final_url": _symbol(module, "assert_allowed_final_url"),
        "request_with_transport": _symbol(module, "request_with_transport"),
    }


def _pubmed_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_sources.pubmed")
    return {
        "PubMedParseError": _symbol(module, "PubMedParseError"),
        "parse_esearch_payload": _symbol(module, "parse_esearch_payload"),
        "parse_efetch_xml": _symbol(module, "parse_efetch_xml"),
    }


def _litvar_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_sources.litvar2")
    return {
        "LitVarParseError": _symbol(module, "LitVarParseError"),
        "parse_gene_mappings": _symbol(module, "parse_gene_mappings"),
    }


def _pmc_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_sources.pmc")
    return {
        "PmcParseError": _symbol(module, "PmcParseError"),
        "parse_fulltext_jats": _symbol(module, "parse_fulltext_jats"),
    }


def _mavedb_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_sources.mavedb")
    return {
        "MaveSourceVerificationError": _symbol(module, "MaveSourceVerificationError"),
        "assert_allowed_mavedb_final_url": _symbol(
            module,
            "assert_allowed_mavedb_final_url",
        ),
        "verify_scoreset": _symbol(module, "verify_scoreset"),
    }


def _igvf_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_sources.igvf")
    return {
        "IgvfVerificationError": _symbol(module, "IgvfVerificationError"),
        "assert_allowed_igvf_metadata_final_url": _symbol(
            module,
            "assert_allowed_igvf_metadata_final_url",
        ),
        "assert_allowed_igvf_download_final_url": _symbol(
            module,
            "assert_allowed_igvf_download_final_url",
        ),
        "verify_analysis_and_file": _symbol(module, "verify_analysis_and_file"),
    }


def _bundle_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_sources.bundle")
    return {
        "BundleBoundaryError": _symbol(module, "BundleBoundaryError"),
        "BundleHashMismatchError": _symbol(module, "BundleHashMismatchError"),
        "StatusVocabularyError": _symbol(module, "StatusVocabularyError"),
        "build_bundle_manifest": _symbol(module, "build_bundle_manifest"),
        "compute_bundle_content_hash": _symbol(module, "compute_bundle_content_hash"),
        "validate_manifest_hash": _symbol(module, "validate_manifest_hash"),
        "_publish_directory_no_replace": _symbol(module, "_publish_directory_no_replace"),
        "_publish_directory_no_replace_via_claim_then_populate": _symbol(
            module,
            "_publish_directory_no_replace_via_claim_then_populate",
        ),
        "write_bundle_run": _symbol(module, "write_bundle_run"),
        "build_pilot_summary": _symbol(module, "build_pilot_summary"),
        "assert_no_forbidden_status_vocabulary": _symbol(
            module,
            "assert_no_forbidden_status_vocabulary",
        ),
    }


def _ingest_api() -> dict[str, Any]:
    module = _load_module("raptor.external.tsc2_sources.ingest")
    return {
        "SourceIngestionError": _symbol(module, "SourceIngestionError"),
        "run_ingestion": _symbol(module, "run_ingestion"),
    }


def _sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _md5_bytes(blob: bytes) -> str:
    return hashlib.md5(blob).hexdigest()  # nosec B303 - required for published MD5 verification


def _pubmed_esearch_json(
    *,
    count: str = "3",
    idlist: list[str] | None = None,
    retmax: str = "2",
) -> str:
    if idlist is None:
        idlist = ["42425971", "40000001"]
    payload = {
        "esearchresult": {
            "count": count,
            "retmax": retmax,
            "retstart": "0",
            "idlist": idlist,
            "querytranslation": "TSC2[Title/Abstract]",
        }
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _pubmed_efetch_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>42425971</PMID>
      <Article>
        <ArticleTitle>TSC2 pathogenic and benign missense functional follow-up in 2026</ArticleTitle>
        <Abstract>
          <AbstractText Label="BACKGROUND">Background sentence.</AbstractText>
          <AbstractText Label="RESULTS">Pathogenic and benign descriptors are preserved in source text.</AbstractText>
        </Abstract>
        <Journal>
          <JournalIssue>
            <PubDate>
              <Year>2026</Year>
              <Month>08</Month>
              <Day>10</Day>
            </PubDate>
          </JournalIssue>
        </Journal>
        <ELocationID EIdType="doi">10.1000/TSC2.2026.001</ELocationID>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>42420000</PMID>
      <Article>
        <ArticleTitle>Secondary TSC2 methods note</ArticleTitle>
        <Abstract>
          <AbstractText>Single paragraph abstract.</AbstractText>
        </Abstract>
        <Journal>
          <JournalIssue>
            <PubDate>
              <Year>2026</Year>
              <Month>09</Month>
              <Day>01</Day>
            </PubDate>
          </JournalIssue>
        </Journal>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""


def _litvar_literal_line(payload: dict[str, Any]) -> str:
    return repr(payload)


def _litvar_lines(payloads: list[dict[str, Any]]) -> str:
    return "".join(_litvar_literal_line(item) + "\n" for item in payloads)


def _pmc_jats_xml(*, with_license: bool) -> str:
    permissions = ""
    if with_license:
        permissions = """
        <permissions>
          <license license-type="open-access">
            <license-p>This article is distributed under the terms of the Creative Commons Attribution License (CC BY 4.0).</license-p>
          </license>
        </permissions>
        """
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<article>
  <front>
    <article-meta>
      <article-id pub-id-type="pmcid">PMC12871146</article-id>
      {permissions}
    </article-meta>
  </front>
  <body>
    <sec>
      <p>Example section text.</p>
    </sec>
  </body>
</article>
"""


def _make_mavedb_metadata(
    *,
    transcript: str = "NM_000548.5",
    license_short: str = "CC0",
    license_version: str = "1.0",
    gene: str = "TSC2",
) -> str:
    payload = {
        "urn": "urn:mavedb:00001201-a-1",
        "targetGenes": [{"name": gene}],
        "methodText": f"Variants based on Refseq transcript {transcript}.",
        "license": {
            "shortName": license_short,
            "version": license_version,
        },
        "numVariants": 208,
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _make_mavedb_scores_csv(variant_count: int = 208) -> bytes:
    rows = ["accession,hgvs_nt,hgvs_splice,hgvs_pro,score"]
    for idx in range(1, variant_count + 1):
        rows.append(f"acc{idx},c.{idx}A>G,,p.X{idx}Y,{0.100 + (idx / 1000):.3f}")
    return ("\n".join(rows) + "\n").encode("utf-8")


def _make_igvf_fixture(
    *,
    analysis_accession: str = "IGVFDS5595BTYJ",
    file_accession: str = "IGVFFI9747KART",
    status: str = "released",
    controlled_access: bool = False,
    assembly: str = "GRCh38",
) -> tuple[str, str, bytes, dict[str, Any]]:
    table = "variant_id\tscore\nNC_000016.10:100:A:G\t0.10\nNC_000016.10:200:C:T\t0.20\n"
    file_bytes = gzip.compress(table.encode("utf-8"), mtime=0)
    md5 = _md5_bytes(file_bytes)
    href = f"/tabular-files/{file_accession}/@@download/{file_accession}.tsv.gz"
    analysis_payload = {
        "accession": analysis_accession,
        "status": status,
    }
    file_payload = {
        "accession": file_accession,
        "status": status,
        "controlled_access": controlled_access,
        "assembly": assembly,
        "file_size": len(file_bytes),
        "md5sum": md5,
        "href": href,
    }
    expected = {
        "analysis_set": analysis_accession,
        "file_accession": file_accession,
        "required_status": "released",
        "required_controlled_access": False,
        "expected_assembly": "GRCh38",
        "expected_file_size": len(file_bytes),
        "expected_md5": md5,
        "expected_href": href,
    }
    return (
        json.dumps(analysis_payload, separators=(",", ":"), sort_keys=True),
        json.dumps(file_payload, separators=(",", ":"), sort_keys=True),
        file_bytes,
        expected,
    )


def _artifact_record(
    *,
    artifact_id: str,
    source_id: str,
    relative_path: str,
    body: bytes,
    verification: str = "HASHED",
) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "source_id": source_id,
        "role": "TEST_ARTIFACT",
        "requested_url": f"https://example.invalid/{artifact_id}",
        "final_url": f"https://example.invalid/{artifact_id}",
        "http_status": 200,
        "media_type": "application/octet-stream",
        "relative_path": relative_path,
        "byte_length": len(body),
        "sha256": _sha256_bytes(body),
        "md5": _md5_bytes(body),
        "fetched_at": "2026-09-09T00:00:00Z",
        "verification": verification,
    }


def _source_record(
    *,
    source_id: str,
    source_kind: str,
    artifact_ids: list[str],
    lifecycle_state: str = "STAGED_VERIFIED",
    licence_state: str = "EXPLICIT_LICENSE_DECLARED",
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_kind": source_kind,
        "lifecycle_state": lifecycle_state,
        "access_state": "PUBLIC",
        "licence_state": licence_state,
        "permitted_use": "NON_CLINICAL_DISCOVERY",
        "identifiers": {"primary": source_id},
        "artifact_ids": artifact_ids,
        "observations": {"note": "fixture"},
        "limitations": [],
    }


def _forbid_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _no_network(*args, **kwargs):
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


def _pubmed_efetch_partial_dates_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>50000001</PMID>
      <Article>
        <ArticleTitle>Year-only TSC2 note</ArticleTitle>
        <Abstract>
          <AbstractText>Year precision is preserved.</AbstractText>
        </Abstract>
        <Journal>
          <JournalIssue>
            <PubDate>
              <Year>2026</Year>
            </PubDate>
          </JournalIssue>
        </Journal>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>50000002</PMID>
      <Article>
        <ArticleTitle>Structured <i>TSC2</i> month-level date</ArticleTitle>
        <Abstract>
          <AbstractText>Nested <i>text</i> remains preserved.</AbstractText>
        </Abstract>
        <Journal>
          <JournalIssue>
            <PubDate>
              <Year>2026</Year>
              <Month>09</Month>
            </PubDate>
          </JournalIssue>
        </Journal>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>50000003</PMID>
      <Article>
        <ArticleTitle>MedlineDate fallback sample</ArticleTitle>
        <Abstract>
          <AbstractText>Structured fields are absent.</AbstractText>
        </Abstract>
        <Journal>
          <JournalIssue>
            <PubDate>
              <MedlineDate>2026 Winter</MedlineDate>
            </PubDate>
          </JournalIssue>
        </Journal>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""


def _replace_query_params(url: str, updates: dict[str, str]) -> str:
    parts = urlsplit(url)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    params.update(updates)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))


def _sensitive_query_url() -> str:
    return (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        "?db=pubmed"
        "&retmode=json"
        "&term=TSC2%5BTitle%2FAbstract%5D"
        "&mindate=2026%2F01%2F01"
        "&maxdate=2026%2F09%2F09"
        "&retmax=100"
        "&datetype=pdat"
        "&api_key=SENTINEL_API_KEY_VALUE"
        "&email=sentinel.user%40example.org"
        "&AWSAccessKeyId=SENTINEL_AWS_ACCESS_KEY_ID"
        "&Signature=SENTINEL_SIGNATURE_VALUE"
        "&x-amz-security-token=SENTINEL_SECURITY_TOKEN"
        "&x-amz-credential=SENTINEL_AMZ_CREDENTIAL"
    )


def _assert_no_secret_values(text: str) -> None:
    lowered = text.lower()
    secret_values = (
        "SENTINEL_API_KEY_VALUE",
        "sentinel.user@example.org",
        "SENTINEL_AWS_ACCESS_KEY_ID",
        "SENTINEL_SIGNATURE_VALUE",
        "SENTINEL_SECURITY_TOKEN",
        "SENTINEL_AMZ_CREDENTIAL",
    )
    for value in secret_values:
        assert value.lower() not in lowered


def _minimal_bundle_manifest_and_payload(
    *,
    source_id: str = "pubmed",
    source_kind: str = "pubmed",
    run_tag: str = "default",
) -> tuple[dict[str, Any], dict[str, bytes]]:
    api = _bundle_api()
    body = f"artifact-{source_id}-{run_tag}".encode("utf-8")
    artifact_id = f"{source_id}-artifact-{run_tag}"
    relative_path = f"{source_id}/{run_tag}.bin"
    artifact = _artifact_record(
        artifact_id=artifact_id,
        source_id=source_id,
        relative_path=relative_path,
        body=body,
        verification="HASHED",
    )
    source = _source_record(
        source_id=source_id,
        source_kind=source_kind,
        artifact_ids=[artifact_id],
    )
    manifest = api["build_bundle_manifest"](
        bundle_id=f"bundle-{run_tag}",
        created_at="2026-09-09T00:00:00Z",
        query={"gene": "TSC2"},
        artifacts=[artifact],
        sources=[source],
        truncation={},
        boundaries={"network": "injected", "external_output_only": True},
    )
    return manifest, {relative_path: body}


def _expected_missing_source_ids(source_ids: list[str]) -> list[str]:
    source_id_set = set(source_ids)
    return [source_id for source_id in REQUIRED_PILOT_SOURCE_IDS if source_id not in source_id_set]


def _artifact_integrity_map(artifacts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        artifact["artifact_id"]: {
            "sha256": artifact["sha256"],
            "md5": artifact["md5"],
            "byte_length": artifact["byte_length"],
            "verification": artifact["verification"],
        }
        for artifact in artifacts
    }


def _assert_hex_digest(value: str, *, length: int) -> None:
    assert isinstance(value, str)
    assert len(value) == length
    int(value, 16)


def _extract_yaml_entry_block(yaml_text: str, *, urn: str) -> str:
    marker = f'- urn: "{urn}"'
    start = yaml_text.find(marker)
    if start == -1:
        pytest.fail(f"source register entry for {urn!r} was not found")
    remainder = yaml_text[start:]
    next_entry = remainder.find("\n  - urn:", len(marker))
    return remainder if next_entry == -1 else remainder[:next_entry]


def test_ac01_url_builders_encode_query_and_enforce_allowlists() -> None:
    api = _endpoint_api()
    query = 'TSC2[Title/Abstract] AND "loss of function"'
    esearch_url = api["build_pubmed_esearch_url"](
        query=query,
        date_start="2026/01/01",
        date_end="2026/09/09",
        retmax=100,
    )
    parts = urlsplit(esearch_url)
    assert parts.scheme == "https"
    assert parts.netloc == "eutils.ncbi.nlm.nih.gov"
    params = parse_qs(parts.query, strict_parsing=True)
    assert params["db"] == ["pubmed"]
    assert params["retmode"] == ["json"]
    assert params["term"] == [query]
    assert params["mindate"] == ["2026/01/01"]
    assert params["maxdate"] == ["2026/09/09"]
    assert params["retmax"] == ["100"]
    assert "term=TSC2%5BTitle%2FAbstract%5D%20AND%20%22loss%20of%20function%22" in esearch_url

    efetch_url = api["build_pubmed_efetch_url"](pmids=["42425971", "40000001"])
    efetch_parts = urlsplit(efetch_url)
    efetch_params = parse_qs(efetch_parts.query, strict_parsing=True)
    assert efetch_parts.scheme == "https"
    assert efetch_parts.netloc == "eutils.ncbi.nlm.nih.gov"
    assert efetch_params["db"] == ["pubmed"]
    assert efetch_params["retmode"] == ["xml"]
    assert efetch_params["id"] == ["42425971,40000001"]

    litvar_url = api["build_litvar2_gene_url"](gene="TSC2")
    litvar_parts = urlsplit(litvar_url)
    assert litvar_parts.scheme == "https"
    assert litvar_parts.netloc == "www.ncbi.nlm.nih.gov"
    assert litvar_parts.path.endswith("/litvar2-api/variant/search/gene/TSC2")

    api["assert_allowed_final_url"](requested_url=esearch_url, final_url=esearch_url)
    with pytest.raises(api["EndpointSecurityError"], match="host|allowlist"):
        api["assert_allowed_final_url"](
            requested_url=esearch_url,
            final_url="https://evil.example.org/redirect",
        )
    with pytest.raises(api["EndpointSecurityError"], match="scheme|allowlist"):
        api["assert_allowed_final_url"](
            requested_url=esearch_url,
            final_url="http://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        )


def test_ac02_transport_is_purely_injected_with_zero_real_network_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _endpoint_api()
    _forbid_real_network(monkeypatch)

    requested_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed"
    body = _pubmed_esearch_json().encode("utf-8")
    seen: list[str] = []

    def fake_transport(url: str) -> dict[str, Any]:
        seen.append(url)
        return {
            "final_url": url,
            "http_status": 200,
            "media_type": "application/json",
            "body": body,
        }

    fetched = api["request_with_transport"](requested_url=requested_url, transport=fake_transport)
    assert seen == [requested_url]
    assert fetched["requested_url"] == requested_url
    assert fetched["final_url"] == requested_url
    assert fetched["http_status"] == 200
    assert fetched["media_type"] == "application/json"
    assert fetched["byte_length"] == len(body)
    assert fetched["sha256"] == _sha256_bytes(body)


def test_ac03_pubmed_esearch_parses_count_pmids_and_truncation() -> None:
    api = _pubmed_api()
    parsed = api["parse_esearch_payload"](
        _pubmed_esearch_json(count="3", idlist=["42425971", "40000001"], retmax="2"),
        expected_db="pubmed",
        required_pmid="42425971",
    )
    assert set(parsed) == {
        "count",
        "pmids",
        "returned_count",
        "is_truncated",
        "required_pmid_present",
    }
    assert parsed["count"] == 3
    assert parsed["pmids"] == ["42425971", "40000001"]
    assert parsed["returned_count"] == 2
    assert parsed["is_truncated"] is True
    assert parsed["required_pmid_present"] is True


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            json.dumps({"retstart": "0"}, separators=(",", ":"), sort_keys=True),
            "esearchresult|top-level",
        ),
        (
            json.dumps({"esearchresult": []}, separators=(",", ":"), sort_keys=True),
            "esearchresult|shape|object",
        ),
        (_pubmed_esearch_json(count="not-a-number"), "count"),
        (_pubmed_esearch_json(idlist=["40000001", "40000002"]), "42425971|required"),
    ],
    ids=[
        "missing-esearchresult-top-level",
        "malformed-esearchresult-shape",
        "malformed-count",
        "missing-required-pmid",
    ],
)
def test_ac03_pubmed_esearch_required_failure_cases(payload: str, message: str) -> None:
    api = _pubmed_api()
    with pytest.raises(api["PubMedParseError"], match=message):
        api["parse_esearch_payload"](
            payload,
            expected_db="pubmed",
            required_pmid="42425971",
        )


def test_ac04_pubmed_efetch_parses_metadata_without_evidence_inference() -> None:
    api = _pubmed_api()
    rows = api["parse_efetch_xml"](_pubmed_efetch_xml())
    assert isinstance(rows, list)
    assert len(rows) == 2
    assert rows[0]["pmid"] == "42425971"
    assert rows[0]["doi"] == "10.1000/TSC2.2026.001"
    assert rows[0]["title"] == "TSC2 pathogenic and benign missense functional follow-up in 2026"
    assert rows[0]["publication_date"] == "2026-08-10"
    assert (
        rows[0]["abstract"]
        == "Background sentence. Pathogenic and benign descriptors are preserved in source text."
    )
    assert rows[1]["pmid"] == "42420000"
    assert rows[1]["doi"] is None

    for row in rows:
        assert set(row) == {"pmid", "doi", "title", "publication_date", "abstract"}


def test_ac05_litvar_rsidless_record_with_id_and_pmids_count_is_accepted_and_projected() -> None:
    api = _litvar_api()
    payload = _litvar_lines(
        [
            {"_id": "litvar@#7249#p.Y893H", "pmids_count": 17, "rsid": None},
        ]
    )
    rows = api["parse_gene_mappings"](payload)
    assert rows == [{"_id": "litvar@#7249#p.Y893H", "rsid": None, "pmids_count": 17}]
    assert all(set(row) == {"_id", "rsid", "pmids_count"} for row in rows)


def test_ac05_litvar_canonical_aggregate_supersedes_narrower_clingen_alias() -> None:
    api = _litvar_api()
    payload = _litvar_lines(
        [
            {"_id": "litvar@rs121907954##", "pmids_count": 11, "rsid": "rs121907954"},
            {
                "_id": "litvar@CA321685#rs121907954##",
                "rsid": "rs121907954",
                "pmids_count": 4,
                "clingen_id": "CA321685",
            },
            {"_id": "litvar@rs587782356##", "pmids_count": 3, "rsid": "rs587782356"},
        ]
    )
    assert api["parse_gene_mappings"](payload) == [
        {"_id": "litvar@rs121907954##", "rsid": "rs121907954", "pmids_count": 11},
        {"_id": "litvar@rs587782356##", "rsid": "rs587782356", "pmids_count": 3},
    ]


def test_ac05_litvar_sole_noncanonical_rsid_record_is_retained() -> None:
    api = _litvar_api()
    payload = _litvar_lines(
        [
            {
                "_id": "litvar@CA987654#rs987654321##",
                "pmids_count": 2,
                "rsid": "rs987654321",
                "clingen_id": "CA987654",
            }
        ]
    )
    assert api["parse_gene_mappings"](payload) == [
        {"_id": "litvar@CA987654#rs987654321##", "rsid": "rs987654321", "pmids_count": 2}
    ]


def test_ac05_litvar_malformed_rsid_fails() -> None:
    api = _litvar_api()
    payload = _litvar_lines(
        [
            {"_id": "litvar@121907954##", "pmids_count": 3, "rsid": "121907954"},
        ]
    )
    with pytest.raises(api["LitVarParseError"], match="rsid"):
        api["parse_gene_mappings"](payload)


def test_ac05_litvar_alias_pmids_count_greater_than_canonical_fails_closed() -> None:
    api = _litvar_api()
    payload = _litvar_lines(
        [
            {"_id": "litvar@rs121907954##", "pmids_count": 3, "rsid": "rs121907954"},
            {
                "_id": "litvar@CA321685#rs121907954##",
                "pmids_count": 4,
                "rsid": "rs121907954",
                "clingen_id": "CA321685",
            },
        ]
    )
    with pytest.raises(api["LitVarParseError"], match="pmids_count|canonical|alias|duplicate|rsid"):
        api["parse_gene_mappings"](payload)


def test_ac05_litvar_multiple_noncanonical_records_without_canonical_are_ambiguous() -> None:
    api = _litvar_api()
    payload = _litvar_lines(
        [
            {
                "_id": "litvar@CA111111#rs121907954##",
                "pmids_count": 3,
                "rsid": "rs121907954",
                "clingen_id": "CA111111",
            },
            {
                "_id": "litvar@CA222222#rs121907954##",
                "pmids_count": 3,
                "rsid": "rs121907954",
                "clingen_id": "CA222222",
            },
        ]
    )
    with pytest.raises(api["LitVarParseError"], match="ambiguous|canonical|duplicate|rsid"):
        api["parse_gene_mappings"](payload)


def test_ac05_litvar_unsafe_line_payload_is_not_executed(tmp_path: Path) -> None:
    api = _litvar_api()
    sentinel = tmp_path / "unsafe_payload_executed.txt"
    unsafe = (
        "__import__('pathlib').Path("
        + json.dumps(str(sentinel))
        + ").write_text('owned', encoding='utf-8')"
    )
    with pytest.raises(api["LitVarParseError"]):
        api["parse_gene_mappings"](unsafe + "\n")
    assert not sentinel.exists()


def test_ac06_pmc_explicit_license_is_preserved_with_raw_xml_hash() -> None:
    api = _pmc_api()
    xml = _pmc_jats_xml(with_license=True)
    parsed = api["parse_fulltext_jats"](xml, expected_pmcid="PMC12871146")
    assert parsed["pmcid"] == "PMC12871146"
    assert "Creative Commons Attribution License (CC BY 4.0)" in parsed["license_text"]
    assert parsed["licence_state"] == "EXPLICIT_LICENSE_DECLARED"
    assert parsed["raw_xml_sha256"] == _sha256_bytes(xml.encode("utf-8"))


def test_ac06_pmc_missing_license_is_review_required() -> None:
    api = _pmc_api()
    xml = _pmc_jats_xml(with_license=False)
    parsed = api["parse_fulltext_jats"](xml, expected_pmcid="PMC12871146")
    assert parsed["pmcid"] == "PMC12871146"
    assert parsed["license_text"] is None
    assert parsed["licence_state"] == "LICENCE_REVIEW_REQUIRED"


def test_ac07_mavedb_verifies_transcript_license_count_and_hash() -> None:
    api = _mavedb_api()
    metadata = _make_mavedb_metadata()
    scores_csv = _make_mavedb_scores_csv(variant_count=208)
    expected_sha256 = _sha256_bytes(scores_csv)
    verified = api["verify_scoreset"](
        metadata_json=metadata,
        scores_csv_bytes=scores_csv,
        expected_gene="TSC2",
        expected_transcript="NM_000548.5",
        expected_variant_count=208,
        expected_license="CC0-1.0",
        expected_sha256=expected_sha256,
    )
    assert verified["gene"] == "TSC2"
    assert verified["transcript"] == "NM_000548.5"
    assert verified["license"] == "CC0-1.0"
    assert verified["variant_count"] == 208
    assert verified["sha256"] == expected_sha256
    assert verified["lifecycle_state"] == "STAGED_VERIFIED"


@pytest.mark.parametrize(
    ("metadata", "scores_csv", "expected_variant_count", "expected_license", "expected_sha", "message"),
    [
        (
            _make_mavedb_metadata(gene="TSC1"),
            _make_mavedb_scores_csv(208),
            208,
            "CC0-1.0",
            _sha256_bytes(_make_mavedb_scores_csv(208)),
            "gene|target",
        ),
        (
            _make_mavedb_metadata(transcript="NM_000548.4"),
            _make_mavedb_scores_csv(208),
            208,
            "CC0-1.0",
            _sha256_bytes(_make_mavedb_scores_csv(208)),
            "transcript",
        ),
        (
            _make_mavedb_metadata(license_short="CC-BY", license_version="4.0"),
            _make_mavedb_scores_csv(208),
            208,
            "CC0-1.0",
            _sha256_bytes(_make_mavedb_scores_csv(208)),
            "license",
        ),
        (
            _make_mavedb_metadata(),
            _make_mavedb_scores_csv(208),
            209,
            "CC0-1.0",
            _sha256_bytes(_make_mavedb_scores_csv(208)),
            "variant|count",
        ),
        (
            _make_mavedb_metadata(),
            _make_mavedb_scores_csv(208),
            208,
            "CC0-1.0",
            "0" * 64,
            "sha|hash",
        ),
    ],
    ids=[
        "gene-drift",
        "transcript-drift",
        "license-drift",
        "row-count-drift",
        "sha256-drift",
    ],
)
def test_ac07_mavedb_drift_failure_cases(
    metadata: str,
    scores_csv: bytes,
    expected_variant_count: int,
    expected_license: str,
    expected_sha: str,
    message: str,
) -> None:
    api = _mavedb_api()
    with pytest.raises(api["MaveSourceVerificationError"], match=message):
        api["verify_scoreset"](
            metadata_json=metadata,
            scores_csv_bytes=scores_csv,
            expected_gene="TSC2",
            expected_transcript="NM_000548.5",
            expected_variant_count=expected_variant_count,
            expected_license=expected_license,
            expected_sha256=expected_sha,
        )


def test_ac08_ac09_igvf_accession_status_access_assembly_size_and_md5_checks() -> None:
    api = _igvf_api()
    analysis_json, file_json, file_bytes, expected = _make_igvf_fixture()
    verified = api["verify_analysis_and_file"](
        analysis_json=analysis_json,
        file_json=file_json,
        file_bytes=file_bytes,
        expected=expected,
    )
    assert verified["analysis_set"] == "IGVFDS5595BTYJ"
    assert verified["file_accession"] == "IGVFFI9747KART"
    assert verified["status"] == "released"
    assert verified["controlled_access"] is False
    assert verified["assembly"] == "GRCh38"
    assert verified["byte_length"] == len(file_bytes)
    assert verified["md5"] == expected["expected_md5"]
    assert verified["href"] == expected["expected_href"]
    assert verified["verification"] == "PUBLISHED_MD5_VERIFIED"


def test_ac08_ac09_igvf_drift_failure_cases() -> None:
    api = _igvf_api()
    analysis_json, file_json, file_bytes, expected = _make_igvf_fixture()
    analysis = json.loads(analysis_json)
    file_meta = json.loads(file_json)

    drift_cases = [
        ("analysis_set", {"analysis": {"accession": "IGVFDS0000XXXX"}}, "analysis|accession"),
        ("file_accession", {"file": {"accession": "IGVFFI0000XXXX"}}, "file|accession"),
        ("status", {"analysis": {"status": "archived"}}, "status"),
        ("controlled_access", {"file": {"controlled_access": True}}, "access|controlled"),
        ("assembly", {"file": {"assembly": "GRCh37"}}, "assembly"),
        ("size", {"file": {"file_size": file_meta["file_size"] + 1}}, "size|byte"),
        ("md5", {"file": {"md5sum": "0" * 32}}, "md5"),
        (
            "href-external",
            {"file": {"href": "https://files.example.org/IGVFFI9747KART.tsv.gz"}},
            "href|download|tabular",
        ),
        (
            "href-mismatched-accession",
            {"file": {"href": "/tabular-files/IGVFFI0000XXXX/@@download/IGVFFI9747KART.tsv.gz"}},
            "href|accession|tabular",
        ),
    ]

    for _name, mutation, message in drift_cases:
        mutated_analysis = dict(analysis)
        mutated_file = dict(file_meta)
        mutated_expected = dict(expected)
        for key, value in mutation.get("analysis", {}).items():
            mutated_analysis[key] = value
        for key, value in mutation.get("file", {}).items():
            mutated_file[key] = value
        with pytest.raises(api["IgvfVerificationError"], match=message):
            api["verify_analysis_and_file"](
                analysis_json=json.dumps(mutated_analysis, separators=(",", ":"), sort_keys=True),
                file_json=json.dumps(mutated_file, separators=(",", ":"), sort_keys=True),
                file_bytes=file_bytes,
                expected=mutated_expected,
            )


def test_ac10_igvf_is_licence_review_required_and_not_classification_ready() -> None:
    igvf_api = _igvf_api()
    bundle_api = _bundle_api()
    analysis_json, file_json, file_bytes, expected = _make_igvf_fixture()
    source = igvf_api["verify_analysis_and_file"](
        analysis_json=analysis_json,
        file_json=file_json,
        file_bytes=file_bytes,
        expected=expected,
    )
    assert source["lifecycle_state"] == "STAGED_LICENCE_REVIEW_REQUIRED"
    assert source["licence_state"] == "REVIEW_REQUIRED"
    bundle_api["assert_no_forbidden_status_vocabulary"]([source])

    forbidden = dict(source)
    forbidden["lifecycle_state"] = "classification_ready"
    with pytest.raises(bundle_api["StatusVocabularyError"], match="classification"):
        bundle_api["assert_no_forbidden_status_vocabulary"]([forbidden])


def test_ac11_output_boundaries_external_create_only_and_symlink_safe(tmp_path: Path) -> None:
    api = _bundle_api()
    body = b"artifact-bytes"
    artifact = _artifact_record(
        artifact_id="pubmed-search-json",
        source_id="pubmed",
        relative_path="pubmed/esearch.json",
        body=body,
    )
    source = _source_record(
        source_id="pubmed",
        source_kind="pubmed",
        artifact_ids=[artifact["artifact_id"]],
    )
    manifest = api["build_bundle_manifest"](
        bundle_id="tsc2-source-pilot-2026-09-09",
        created_at="2026-09-09T00:00:00Z",
        query={"gene": "TSC2"},
        artifacts=[artifact],
        sources=[source],
        truncation={"pubmed": {"count": 3, "returned_count": 2, "is_truncated": True}},
        boundaries={"network": "injected", "external_output_only": True},
    )

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    inside_repo_output = repo_root / "external"
    inside_repo_output.mkdir()
    with pytest.raises(api["BundleBoundaryError"], match="external|repository"):
        api["write_bundle_run"](
            repo_root=repo_root,
            output_root=inside_repo_output,
            run_name="tsc2-source-pilot-2026-09-09",
            manifest=manifest,
            artifact_payloads={artifact["relative_path"]: body},
        )

    external_output = tmp_path / "outside"
    external_output.mkdir()
    preexisting = external_output / "tsc2-source-pilot-2026-09-09"
    preexisting.mkdir()
    with pytest.raises(api["BundleBoundaryError"], match="exists|create-only"):
        api["write_bundle_run"](
            repo_root=repo_root,
            output_root=external_output,
            run_name="tsc2-source-pilot-2026-09-09",
            manifest=manifest,
            artifact_payloads={artifact["relative_path"]: body},
        )

    external_output_symlink = tmp_path / "outside-symlink"
    external_output_symlink.mkdir()
    real_target = tmp_path / "real-target"
    real_target.mkdir()
    run_leaf = external_output_symlink / "tsc2-source-pilot-2026-09-09"
    run_leaf.symlink_to(real_target, target_is_directory=True)
    with pytest.raises(api["BundleBoundaryError"], match="symlink|reparse"):
        api["write_bundle_run"](
            repo_root=repo_root,
            output_root=external_output_symlink,
            run_name="tsc2-source-pilot-2026-09-09",
            manifest=manifest,
            artifact_payloads={artifact["relative_path"]: body},
        )


def test_ac11_partial_failure_publishes_no_manifest(tmp_path: Path) -> None:
    api = _bundle_api()
    body_a = b"a" * 16
    body_b = b"b" * 32
    artifact_a = _artifact_record(
        artifact_id="igvf-analysis-json",
        source_id="igvf_vamp_seq",
        relative_path="igvf/analysis.json",
        body=body_a,
        verification="METADATA_ONLY",
    )
    artifact_b = _artifact_record(
        artifact_id="igvf-download-tsv-gz",
        source_id="igvf_vamp_seq",
        relative_path="igvf/IGVFFI9747KART.tsv.gz",
        body=body_b,
        verification="PUBLISHED_MD5_VERIFIED",
    )
    source = _source_record(
        source_id="igvf_vamp_seq",
        source_kind="igvf",
        artifact_ids=[artifact_a["artifact_id"], artifact_b["artifact_id"]],
        lifecycle_state="STAGED_LICENCE_REVIEW_REQUIRED",
        licence_state="REVIEW_REQUIRED",
    )
    manifest = api["build_bundle_manifest"](
        bundle_id="tsc2-source-pilot-2026-09-09",
        created_at="2026-09-09T00:00:00Z",
        query={"gene": "TSC2"},
        artifacts=[artifact_a, artifact_b],
        sources=[source],
        truncation={},
        boundaries={"network": "injected", "external_output_only": True},
    )
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    output_root = tmp_path / "external-root"
    output_root.mkdir()
    run_name = "tsc2-source-pilot-2026-09-09"

    interrupted_payload = body_b[:-3]
    with pytest.raises(api["BundleHashMismatchError"], match="artifact|hash|byte"):
        api["write_bundle_run"](
            repo_root=repo_root,
            output_root=output_root,
            run_name=run_name,
            manifest=manifest,
            artifact_payloads={
                artifact_a["relative_path"]: body_a,
                artifact_b["relative_path"]: interrupted_payload,
            },
        )

    manifest_path = output_root / run_name / MANIFEST_FILENAME
    assert not manifest_path.exists()


def test_ac12_manifest_hash_is_key_order_invariant_and_byte_sensitive() -> None:
    api = _bundle_api()
    body = b"pubmed-esearch"
    artifact = _artifact_record(
        artifact_id="pubmed-esearch-json",
        source_id="pubmed",
        relative_path="pubmed/esearch.json",
        body=body,
    )
    source_a = _source_record(
        source_id="pubmed",
        source_kind="pubmed",
        artifact_ids=[artifact["artifact_id"]],
    )
    source_b = {
        "limitations": [],
        "observations": {"note": "fixture"},
        "artifact_ids": [artifact["artifact_id"]],
        "identifiers": {"primary": "pubmed"},
        "permitted_use": "NON_CLINICAL_DISCOVERY",
        "licence_state": "EXPLICIT_LICENSE_DECLARED",
        "access_state": "PUBLIC",
        "lifecycle_state": "STAGED_VERIFIED",
        "source_kind": "pubmed",
        "source_id": "pubmed",
    }

    manifest_a = api["build_bundle_manifest"](
        bundle_id="bundle-a",
        created_at="2026-09-09T00:00:00Z",
        query={"gene": "TSC2"},
        artifacts=[artifact],
        sources=[source_a],
        truncation={"pubmed": {"count": 3, "returned_count": 2, "is_truncated": True}},
        boundaries={"network": "injected", "external_output_only": True},
    )
    manifest_b = api["build_bundle_manifest"](
        bundle_id="bundle-a",
        created_at="2026-09-09T00:00:00Z",
        query={"gene": "TSC2"},
        artifacts=[artifact],
        sources=[source_b],
        truncation={"pubmed": {"count": 3, "returned_count": 2, "is_truncated": True}},
        boundaries={"network": "injected", "external_output_only": True},
    )
    assert manifest_a["content_hash"] == manifest_b["content_hash"]
    assert api["compute_bundle_content_hash"](manifest_a) == manifest_a["content_hash"]

    mutated_artifact = dict(artifact)
    changed_body = b"pubmed-esearch-mutated"
    mutated_artifact["sha256"] = _sha256_bytes(changed_body)
    mutated_artifact["md5"] = _md5_bytes(changed_body)
    mutated_artifact["byte_length"] = len(changed_body)
    manifest_c = api["build_bundle_manifest"](
        bundle_id="bundle-a",
        created_at="2026-09-09T00:00:00Z",
        query={"gene": "TSC2"},
        artifacts=[mutated_artifact],
        sources=[source_a],
        truncation={"pubmed": {"count": 3, "returned_count": 2, "is_truncated": True}},
        boundaries={"network": "injected", "external_output_only": True},
    )
    assert manifest_c["content_hash"] != manifest_a["content_hash"]


def test_ac12_manifest_hash_mismatch_is_reported() -> None:
    api = _bundle_api()
    body = b"litvar"
    artifact = _artifact_record(
        artifact_id="litvar2-gene-jsonl",
        source_id="litvar2",
        relative_path="litvar2/gene-TSC2.jsonl",
        body=body,
    )
    source = _source_record(
        source_id="litvar2",
        source_kind="litvar2",
        artifact_ids=[artifact["artifact_id"]],
    )
    manifest = api["build_bundle_manifest"](
        bundle_id="bundle-hash-check",
        created_at="2026-09-09T00:00:00Z",
        query={"gene": "TSC2"},
        artifacts=[artifact],
        sources=[source],
        truncation={},
        boundaries={"network": "injected", "external_output_only": True},
    )
    tampered = dict(manifest)
    tampered["content_hash"] = "0" * 64
    with pytest.raises(api["BundleHashMismatchError"], match="content_hash|mismatch"):
        api["validate_manifest_hash"](tampered)


def test_ac13_no_forbidden_domain_imports_in_tsc2_package_or_operator() -> None:
    if not PACKAGE_ROOT.exists():
        pytest.fail(f"TSC2 source package is not implemented: {PACKAGE_ROOT}")
    if not OPERATOR_SCRIPT.is_file():
        pytest.fail(f"TSC2 source operator script is not implemented: {OPERATOR_SCRIPT}")

    offenders: list[str] = []
    targets = [* _iter_python_files(PACKAGE_ROOT), OPERATOR_SCRIPT]
    for path in targets:
        for imported, lineno in _module_imports(path):
            if any(
                imported == blocked or imported.startswith(blocked + ".")
                for blocked in FORBIDDEN_IMPORT_PREFIXES
            ):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}:{imported}")
    assert not offenders, "forbidden import boundary crossings:\n" + "\n".join(offenders)


def test_ac13_retired_pmc_oa_webservice_path_is_not_used() -> None:
    if not PACKAGE_ROOT.exists():
        pytest.fail(f"TSC2 source package is not implemented: {PACKAGE_ROOT}")
    if not OPERATOR_SCRIPT.is_file():
        pytest.fail(f"TSC2 source operator script is not implemented: {OPERATOR_SCRIPT}")

    offenders: list[str] = []
    targets = [*_iter_python_files(PACKAGE_ROOT), OPERATOR_SCRIPT]
    for path in targets:
        text = path.read_text(encoding="utf-8").lower()
        if RETIRED_PMC_OA_ENDPOINT_PATH in text:
            offenders.append(f"{path.relative_to(REPO_ROOT)}:{RETIRED_PMC_OA_ENDPOINT_PATH}")

    assert not offenders, "retired PMC OA Web Service endpoint path must not be referenced:\n" + "\n".join(
        offenders
    )


def test_ac14_committed_pilot_summary_is_aggregate_only() -> None:
    api = _bundle_api()
    pubmed_body = _pubmed_esearch_json().encode("utf-8")
    litvar_body = _litvar_lines(
        [{"_id": "litvar@rs121907954##", "pmids_count": 3, "rsid": "rs121907954"}]
    ).encode("utf-8")
    artifacts = [
        _artifact_record(
            artifact_id="pubmed-search",
            source_id="pubmed",
            relative_path="pubmed/esearch.json",
            body=pubmed_body,
        ),
        _artifact_record(
            artifact_id="litvar-gene",
            source_id="litvar2",
            relative_path="litvar2/TSC2.jsonl",
            body=litvar_body,
        ),
    ]
    sources = [
        _source_record(
            source_id="pubmed",
            source_kind="pubmed",
            artifact_ids=["pubmed-search"],
        ),
        _source_record(
            source_id="litvar2",
            source_kind="litvar2",
            artifact_ids=["litvar-gene"],
        ),
    ]
    manifest = api["build_bundle_manifest"](
        bundle_id="tsc2-source-pilot-2026-09-09",
        created_at="2026-09-09T00:00:00Z",
        query={"gene": "TSC2"},
        artifacts=artifacts,
        sources=sources,
        truncation={"pubmed": {"count": 3, "returned_count": 2, "is_truncated": True}},
        boundaries={"network": "injected", "external_output_only": True},
    )
    summary = api["build_pilot_summary"](manifest)
    source_ids = [source["source_id"] for source in sources]
    expected_source_states = {
        source["source_id"]: {
            "source_kind": source["source_kind"],
            "lifecycle_state": source["lifecycle_state"],
            "access_state": source["access_state"],
            "licence_state": source["licence_state"],
        }
        for source in sources
    }
    expected_source_observations = {
        source["source_id"]: source["observations"] for source in sources
    }

    assert summary["schema"] == "raptor.external.tsc2_source_pilot_summary.v1"
    assert set(summary) == {
        "schema",
        "bundle_id",
        "manifest_content_hash",
        "counts",
        "source_ids",
        "missing_source_ids",
        "truncation",
        "source_states",
        "source_observations",
        "artifact_integrity",
        "normalization_gaps",
    }
    assert "artifact_hashes" not in summary
    assert summary["bundle_id"] == manifest["bundle_id"]
    assert summary["manifest_content_hash"] == manifest["content_hash"]
    assert summary["counts"] == {"sources": 2, "artifacts": 2}
    assert summary["source_ids"] == source_ids
    assert summary["missing_source_ids"] == _expected_missing_source_ids(source_ids)
    assert summary["truncation"] == manifest["truncation"]
    assert summary["source_states"] == expected_source_states
    assert summary["source_observations"] == expected_source_observations
    assert summary["artifact_integrity"] == _artifact_integrity_map(artifacts)

    blob = json.dumps(summary, sort_keys=True).lower()
    forbidden_payload_tokens = (
        "requested_url",
        "final_url",
        "variant_id",
        "hgvs",
        "full_text",
        "abstract_text",
        "patient",
        "api_key",
        "awsaccesskeyid",
        "x-amz-signature",
        "classification",
        "pathogenic",
        "benign",
        "ps3",
        "bs3",
    )
    assert not any(token in blob for token in forbidden_payload_tokens)


def test_ac15_forbidden_clinical_or_acmg_status_vocabulary_is_rejected() -> None:
    api = _bundle_api()
    valid = [
        _source_record(
            source_id="pubmed",
            source_kind="pubmed",
            artifact_ids=["pubmed-search"],
            lifecycle_state="STAGED_VERIFIED",
            licence_state="EXPLICIT_LICENSE_DECLARED",
        ),
        _source_record(
            source_id="igvf_vamp_seq",
            source_kind="igvf",
            artifact_ids=["igvf-download"],
            lifecycle_state="STAGED_LICENCE_REVIEW_REQUIRED",
            licence_state="REVIEW_REQUIRED",
        ),
    ]
    api["assert_no_forbidden_status_vocabulary"](valid)

    for forbidden in FORBIDDEN_STATUS_TOKENS:
        invalid = [dict(valid[0])]
        invalid[0]["lifecycle_state"] = forbidden
        with pytest.raises(api["StatusVocabularyError"], match=forbidden.split()[0]):
            api["assert_no_forbidden_status_vocabulary"](invalid)


def test_ac16_source_specific_failure_and_no_endpoint_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _ingest_api()
    _forbid_real_network(monkeypatch)

    pubmed_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        "?db=pubmed&retmode=json&retmax=100&term=TSC2%5BTitle%2FAbstract%5D"
    )
    plan = {
        "bundle_id": "tsc2-source-pilot-2026-09-09",
        "created_at": "2026-09-09T00:00:00Z",
        "query": {"gene": "TSC2"},
        "sources": [
            {
                "source_id": "pubmed",
                "source_kind": "pubmed",
                "request_url": pubmed_url,
                "required_pmid": "42425971",
            }
        ],
    }
    seen_urls: list[str] = []
    bad_payload = _pubmed_esearch_json(count="bad-count")

    def fake_transport(url: str) -> dict[str, Any]:
        seen_urls.append(url)
        if url != pubmed_url:
            raise AssertionError(f"unexpected endpoint substitution: {url}")
        return {
            "final_url": url,
            "http_status": 200,
            "media_type": "application/json",
            "body": bad_payload.encode("utf-8"),
        }

    with pytest.raises(api["SourceIngestionError"]) as exc:
        api["run_ingestion"](
            plan=plan,
            transport=fake_transport,
            repo_root=tmp_path / "repo",
            output_root=tmp_path / "external",
            run_name="tsc2-source-pilot-2026-09-09",
        )

    err = exc.value
    assert getattr(err, "source_id", None) == "pubmed"
    assert getattr(err, "invariant", None) is not None
    message = str(err).lower()
    assert "pubmed" in message
    assert "count" in message or "pmid" in message
    assert pubmed_url in str(err)
    assert seen_urls == [pubmed_url]


def test_ac04_pubmed_valid_partial_dates_and_medline_date_preserve_precision_without_invention() -> None:
    api = _pubmed_api()
    rows = api["parse_efetch_xml"](_pubmed_efetch_partial_dates_xml())
    by_pmid = {row["pmid"]: row for row in rows}
    assert set(by_pmid) == {"50000001", "50000002", "50000003"}

    expected_fields = {
        "pmid",
        "doi",
        "title",
        "publication_date",
        "publication_date_precision",
        "publication_date_raw",
        "abstract",
    }
    for row in rows:
        assert set(row) == expected_fields

    year_only = by_pmid["50000001"]
    assert year_only["publication_date"] == "2026"
    assert str(year_only["publication_date_precision"]).lower() in {"year", "yyyy"}
    assert year_only["publication_date_raw"] == "2026"

    year_month = by_pmid["50000002"]
    assert year_month["publication_date"] == "2026-09"
    assert year_month["publication_date"] != "2026-09-01"
    assert str(year_month["publication_date_precision"]).lower() in {
        "month",
        "year-month",
        "yyyy-mm",
    }
    assert year_month["publication_date_raw"] == "2026-09"
    assert year_month["title"] == "Structured TSC2 month-level date"
    assert year_month["abstract"] == "Nested text remains preserved."

    medline_fallback = by_pmid["50000003"]
    assert medline_fallback["publication_date"] == "2026 Winter"
    assert str(medline_fallback["publication_date_precision"]).lower() in {
        "medline",
        "medline-date",
        "medlinedate",
        "text",
    }
    assert medline_fallback["publication_date_raw"] == "2026 Winter"


def test_ac05_litvar_optional_clingen_id_is_accepted_and_projected() -> None:
    api = _litvar_api()
    payload = _litvar_lines(
        [
            {
                "_id": "litvar@rs121907954##",
                "rsid": "rs121907954",
                "pmids_count": 3,
                "clingen_id": "CA123456",
            },
            {
                "_id": "litvar@rs587782356##",
                "rsid": "rs587782356",
                "pmids_count": 1,
                "clingen_id": "CA654321",
            },
        ]
    )
    assert api["parse_gene_mappings"](payload) == [
        {"_id": "litvar@rs121907954##", "rsid": "rs121907954", "pmids_count": 3},
        {"_id": "litvar@rs587782356##", "rsid": "rs587782356", "pmids_count": 1},
    ]


def test_ac05_litvar_unknown_extra_field_is_rejected_even_when_clingen_id_is_present() -> None:
    api = _litvar_api()
    payload = _litvar_lines(
        [
            {
                "_id": "litvar@rs121907954##",
                "rsid": "rs121907954",
                "pmids_count": 3,
                "clingen_id": "CA123456",
                "unexpected_field": "must-fail",
            },
        ]
    )
    with pytest.raises(api["LitVarParseError"], match="required fields|exact"):
        api["parse_gene_mappings"](payload)


def test_ac05_litvar_ingestion_observations_report_mapping_and_rsid_split_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ingest_api = _ingest_api()
    endpoint_api = _endpoint_api()
    ingest_module = _load_module("raptor.external.tsc2_sources.ingest")
    request_url = endpoint_api["build_litvar2_gene_url"](gene="TSC2")
    plan = {
        "bundle_id": "litvar-observation-counts-v104",
        "created_at": "2026-09-11T00:00:00Z",
        "query": {"gene": "TSC2"},
        "sources": [
            {
                "source_id": "litvar2",
                "source_kind": "litvar2",
                "request_url": request_url,
                "gene": "TSC2",
            }
        ],
    }
    parsed_rows = [
        {"_id": "litvar@rs121907954##", "rsid": "rs121907954", "pmids_count": 4},
        {"_id": "litvar@#7249#p.Y893H", "rsid": None, "pmids_count": 1},
    ]

    monkeypatch.setattr(ingest_module, "parse_gene_mappings", lambda _payload: parsed_rows)

    def fake_transport(url: str) -> dict[str, Any]:
        assert url == request_url
        return {
            "final_url": request_url,
            "http_status": 200,
            "media_type": "application/json",
            "body": b"{}",
        }

    result = ingest_api["run_ingestion"](
        plan=plan,
        transport=fake_transport,
        repo_root=tmp_path / "repo",
        output_root=tmp_path / "external",
        run_name="litvar-observation-counts-v104",
    )

    observations = result["manifest"]["sources"][0]["observations"]
    assert observations["mapping_count"] == 2
    assert observations["rsid_mapping_count"] == 1
    assert observations["rsidless_mapping_count"] == 1
    assert "rsid_count" not in observations


def test_ac01_ac03_pubmed_esearch_builder_includes_datetype_pdat() -> None:
    api = _endpoint_api()
    esearch_url = api["build_pubmed_esearch_url"](
        query="TSC2[Title/Abstract]",
        date_start="2026/01/01",
        date_end="2026/09/09",
        retmax=100,
    )
    params = parse_qs(urlsplit(esearch_url).query, strict_parsing=True)
    assert params["datetype"] == ["pdat"]


@pytest.mark.parametrize(
    ("updated_key", "updated_value"),
    [
        ("term", "TSC1[Title/Abstract]"),
        ("mindate", "2025/01/01"),
        ("maxdate", "2026/12/31"),
        ("datetype", "edat"),
        ("retmax", "250"),
    ],
    ids=[
        "term-substitution",
        "mindate-substitution",
        "maxdate-substitution",
        "datetype-substitution",
        "retmax-substitution",
    ],
)
def test_ac03_pubmed_esearch_final_url_rejects_source_defining_query_substitution(
    updated_key: str,
    updated_value: str,
) -> None:
    api = _endpoint_api()
    requested_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        "?db=pubmed"
        "&retmode=json"
        "&term=TSC2%5BTitle%2FAbstract%5D"
        "&mindate=2026%2F01%2F01"
        "&maxdate=2026%2F09%2F09"
        "&datetype=pdat"
        "&retmax=100"
    )
    final_url = _replace_query_params(requested_url, {updated_key: updated_value})
    with pytest.raises(api["EndpointSecurityError"]):
        api["assert_allowed_final_url"](requested_url=requested_url, final_url=final_url)


def test_ac03_pubmed_efetch_final_url_rejects_changed_pmid_set() -> None:
    api = _endpoint_api()
    requested_url = api["build_pubmed_efetch_url"](pmids=["42425971", "40000001"])
    final_url = api["build_pubmed_efetch_url"](pmids=["42425971", "40000002"])
    with pytest.raises(api["EndpointSecurityError"]):
        api["assert_allowed_final_url"](requested_url=requested_url, final_url=final_url)


@pytest.mark.parametrize(
    ("requested_url", "final_url"),
    [
        (
            "https://api.mavedb.org/api/v1/score-sets/urn:mavedb:00001201-a-1",
            "https://api.mavedb.org/api/v1/score-sets/urn:mavedb:99990000-z-9",
        ),
        (
            "https://api.mavedb.org/api/v1/score-sets/urn:mavedb:00001201-a-1/scores",
            "https://api.mavedb.org/api/v1/score-sets/urn:mavedb:99990000-z-9/scores",
        ),
    ],
    ids=["metadata-urn-substitution", "scores-path-substitution"],
)
def test_ac07_mavedb_final_url_rejects_scoreset_identity_substitution(
    requested_url: str,
    final_url: str,
) -> None:
    api = _mavedb_api()
    with pytest.raises(api["MaveSourceVerificationError"]):
        api["assert_allowed_mavedb_final_url"](requested_url=requested_url, final_url=final_url)


def test_ac08_igvf_metadata_final_url_rejects_accession_path_substitution() -> None:
    api = _igvf_api()
    requested_url = "https://api.data.igvf.org/analysis-sets/IGVFDS5595BTYJ/"
    final_url = "https://api.data.igvf.org/analysis-sets/IGVFDS1782FCXW/"
    with pytest.raises(api["IgvfVerificationError"]):
        api["assert_allowed_igvf_metadata_final_url"](requested_url=requested_url, final_url=final_url)


def test_ac08_igvf_download_final_url_rejects_s3_object_substitution() -> None:
    api = _igvf_api()
    requested_url = (
        "https://api.data.igvf.org/tabular-files/IGVFFI9747KART/"
        "@@download/IGVFFI9747KART.tsv.gz"
    )
    final_url = (
        "https://igvf-public.s3.amazonaws.com/tabular-files/IGVFFI3097DFGF/"
        "@@download/IGVFFI3097DFGF.tsv.gz?X-Amz-Signature=opaque"
    )
    with pytest.raises(api["IgvfVerificationError"]):
        api["assert_allowed_igvf_download_final_url"](requested_url=requested_url, final_url=final_url)


def test_ac16_source_ingestion_error_and_cli_rendering_redact_sensitive_values() -> None:
    api = _ingest_api()
    err = api["SourceIngestionError"](
        source_id="pubmed",
        invariant="TransportTimeout",
        message="simulated transport timeout",
        request_url=_sensitive_query_url(),
    )
    rendered_error = str(err)
    rendered_cli = (
        f"ERROR: source ingestion failed for source_id={err.source_id!r} "
        f"invariant={err.invariant!r}: {err}"
    )

    _assert_no_secret_values(rendered_error)
    _assert_no_secret_values(rendered_cli)

    lowered = rendered_error.lower()
    for redacted_key in (
        "api_key=redacted",
        "email=redacted",
        "awsaccesskeyid=redacted",
        "signature=redacted",
        "x-amz-security-token=redacted",
        "x-amz-credential=redacted",
    ):
        assert redacted_key in lowered
    assert "eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi" in rendered_error


@pytest.mark.parametrize(
    ("case_name", "transport"),
    [
        (
            "non-200-status",
            lambda url: {
                "final_url": url,
                "http_status": 503,
                "media_type": "application/json",
                "body": b"{}",
            },
        ),
        (
            "missing-required-field",
            lambda url: {
                "final_url": url,
                "http_status": 200,
                "body": b"{}",
            },
        ),
        (
            "wrong-field-type",
            lambda _url: {
                "final_url": 123,
                "http_status": "200",
                "media_type": "application/json",
                "body": b"{}",
            },
        ),
        (
            "non-bytes-body",
            lambda url: {
                "final_url": url,
                "http_status": 200,
                "media_type": "application/json",
                "body": "{}",
            },
        ),
        (
            "blank-media-type",
            lambda url: {
                "final_url": url,
                "http_status": 200,
                "media_type": "   ",
                "body": b"{}",
            },
        ),
        (
            "transport-exception",
            lambda _url: (_ for _ in ()).throw(TimeoutError("simulated timeout")),
        ),
    ],
    ids=[
        "non-200-status",
        "missing-required-field",
        "wrong-field-type",
        "non-bytes-body",
        "blank-media-type",
        "transport-exception",
    ],
)
def test_ac16_request_with_transport_rejects_invalid_results_with_typed_errors(
    case_name: str,
    transport,
) -> None:
    api = _endpoint_api()
    requested_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        "?db=pubmed&retmode=json"
    )
    with pytest.raises(Exception) as exc:
        api["request_with_transport"](requested_url=requested_url, transport=transport)
    assert (
        type(exc.value).__module__ != "builtins"
    ), f"{case_name} must raise a typed domain error, not {type(exc.value).__name__}"
    assert type(exc.value).__name__.endswith("Error")


def test_ac16_run_ingestion_wraps_transport_exception_with_sanitized_url(
    tmp_path: Path,
) -> None:
    api = _ingest_api()
    plan = {
        "bundle_id": "transport-failure-bundle",
        "created_at": "2026-09-09T00:00:00Z",
        "query": {"gene": "TSC2"},
        "sources": [
            {
                "source_id": "pubmed",
                "source_kind": "pubmed",
                "request_url": _sensitive_query_url(),
                "required_pmid": "42425971",
            }
        ],
    }

    def failing_transport(_url: str) -> dict[str, Any]:
        raise TimeoutError("simulated timeout with SENTINEL_SIGNATURE_VALUE")

    with pytest.raises(api["SourceIngestionError"]) as exc:
        api["run_ingestion"](
            plan=plan,
            transport=failing_transport,
            repo_root=tmp_path / "repo",
            output_root=tmp_path / "external",
            run_name="transport-failure-run",
        )

    err = exc.value
    assert getattr(err, "source_id", None) == "pubmed"
    assert getattr(err, "invariant", None)
    rendered = str(err)
    _assert_no_secret_values(rendered)
    assert "redacted" in rendered.lower()
    assert "eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi" in rendered


def test_ac11_write_bundle_run_rejects_nested_run_name(tmp_path: Path) -> None:
    api = _bundle_api()
    manifest, payloads = _minimal_bundle_manifest_and_payload(run_tag="nested-run-name")
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    output_root = tmp_path / "external-root"
    output_root.mkdir()

    with pytest.raises(api["BundleBoundaryError"]):
        api["write_bundle_run"](
            repo_root=repo_root,
            output_root=output_root,
            run_name="nested/run-name",
            manifest=manifest,
            artifact_payloads=payloads,
        )


def test_ac11_write_bundle_run_rejects_absolute_run_name(tmp_path: Path) -> None:
    api = _bundle_api()
    manifest, payloads = _minimal_bundle_manifest_and_payload(run_tag="absolute-run-name")
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    output_root = tmp_path / "external-root"
    output_root.mkdir()
    absolute_run_name = str((tmp_path / "escaped-final-run").resolve())

    with pytest.raises(api["BundleBoundaryError"]):
        api["write_bundle_run"](
            repo_root=repo_root,
            output_root=output_root,
            run_name=absolute_run_name,
            manifest=manifest,
            artifact_payloads=payloads,
        )


def test_ac11_write_bundle_run_rejects_output_root_symlink(tmp_path: Path) -> None:
    api = _bundle_api()
    manifest, payloads = _minimal_bundle_manifest_and_payload(run_tag="symlink-root")
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    real_output_root = tmp_path / "real-output-root"
    real_output_root.mkdir()
    symlink_output_root = tmp_path / "linked-output-root"
    symlink_output_root.symlink_to(real_output_root, target_is_directory=True)

    with pytest.raises(api["BundleBoundaryError"]):
        api["write_bundle_run"](
            repo_root=repo_root,
            output_root=symlink_output_root,
            run_name="safe-run",
            manifest=manifest,
            artifact_payloads=payloads,
        )


def test_ac11_write_bundle_run_rejects_symlinked_output_ancestry(tmp_path: Path) -> None:
    api = _bundle_api()
    manifest, payloads = _minimal_bundle_manifest_and_payload(run_tag="symlink-ancestor")
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    real_ancestor = tmp_path / "real-ancestor"
    real_ancestor.mkdir()
    symlink_ancestor = tmp_path / "symlink-ancestor"
    symlink_ancestor.symlink_to(real_ancestor, target_is_directory=True)
    output_root = symlink_ancestor / "child-output-root"

    with pytest.raises(api["BundleBoundaryError"]):
        api["write_bundle_run"](
            repo_root=repo_root,
            output_root=output_root,
            run_name="safe-run",
            manifest=manifest,
            artifact_payloads=payloads,
        )


def test_ac11_concurrent_final_path_creation_preserves_competing_sentinel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _bundle_api()
    bundle_module = _load_module("raptor.external.tsc2_sources.bundle")
    manifest, payloads = _minimal_bundle_manifest_and_payload(run_tag="concurrent-writer")
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    output_root = tmp_path / "external-root"
    output_root.mkdir()
    run_name = "concurrent-run"
    final_run_dir = output_root / run_name
    competing_sentinel = final_run_dir / "COMPETING_WRITER_SENTINEL.txt"
    sentinel_value = "keep-existing-writer-output"
    real_publish_directory_no_replace = api["_publish_directory_no_replace"]

    def fake_publish_directory_no_replace(
        staging_dir: str | Path, destination_dir: str | Path
    ) -> None:
        destination = Path(destination_dir)
        destination.mkdir(parents=True, exist_ok=True)
        competing_sentinel.write_text(sentinel_value, encoding="utf-8")
        real_publish_directory_no_replace(staging_dir, destination_dir)

    monkeypatch.setattr(
        bundle_module,
        "_publish_directory_no_replace",
        fake_publish_directory_no_replace,
    )

    with pytest.raises(Exception) as exc:
        api["write_bundle_run"](
            repo_root=repo_root,
            output_root=output_root,
            run_name=run_name,
            manifest=manifest,
            artifact_payloads=payloads,
        )

    assert competing_sentinel.read_text(encoding="utf-8") == sentinel_value
    assert not (final_run_dir / MANIFEST_FILENAME).exists()
    assert isinstance(exc.value, api["BundleBoundaryError"])


def test_ac11_empty_competing_final_dir_before_publish_is_not_clobbered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _bundle_api()
    bundle_module = _load_module("raptor.external.tsc2_sources.bundle")
    manifest, payloads = _minimal_bundle_manifest_and_payload(run_tag="empty-competing-dir")
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    output_root = tmp_path / "external-root"
    output_root.mkdir()
    run_name = "empty-competing-dir-run"
    final_run_dir = output_root / run_name

    real_publish_directory_no_replace = api["_publish_directory_no_replace"]

    def fake_publish_directory_no_replace(
        staging_dir: str | Path, destination_dir: str | Path
    ) -> None:
        destination = Path(destination_dir)
        destination.mkdir(parents=True, exist_ok=False)
        real_publish_directory_no_replace(staging_dir, destination_dir)

    monkeypatch.setattr(
        bundle_module,
        "_publish_directory_no_replace",
        fake_publish_directory_no_replace,
    )

    with pytest.raises(api["BundleBoundaryError"]):
        api["write_bundle_run"](
            repo_root=repo_root,
            output_root=output_root,
            run_name=run_name,
            manifest=manifest,
            artifact_payloads=payloads,
        )

    assert final_run_dir.exists()
    assert list(final_run_dir.iterdir()) == []
    assert not (final_run_dir / MANIFEST_FILENAME).exists()
    assert not list(output_root.glob(f".{run_name}.staging-*"))


def test_ac11_atomic_publication_failure_cleans_staging_dir_and_publishes_no_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _bundle_api()
    bundle_module = _load_module("raptor.external.tsc2_sources.bundle")
    manifest, payloads = _minimal_bundle_manifest_and_payload(run_tag="replace-failure")
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    output_root = tmp_path / "external-root"
    output_root.mkdir()
    run_name = "replace-failure-run"
    final_run_dir = output_root / run_name

    def fake_publish_directory_no_replace(
        _staging_dir: str | Path, _destination_dir: str | Path
    ) -> None:
        raise OSError("simulated atomic publication failure")

    monkeypatch.setattr(
        bundle_module,
        "_publish_directory_no_replace",
        fake_publish_directory_no_replace,
    )

    with pytest.raises(Exception):
        api["write_bundle_run"](
            repo_root=repo_root,
            output_root=output_root,
            run_name=run_name,
            manifest=manifest,
            artifact_payloads=payloads,
        )

    assert not final_run_dir.exists()
    assert not list(output_root.glob(f".{run_name}.staging-*"))
    assert not (final_run_dir / MANIFEST_FILENAME).exists()


def test_ac11_fallback_claim_then_populate_successfully_publishes_and_cleans_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _bundle_api()
    bundle_module = _load_module("raptor.external.tsc2_sources.bundle")
    staging_dir = tmp_path / "staging"
    destination_dir = tmp_path / "final-run"
    nested_relpath = Path("artifacts") / "nested" / "payload.bin"
    nested_payload = b"nested-payload-bytes"
    nested_path = staging_dir / nested_relpath
    nested_path.parent.mkdir(parents=True, exist_ok=True)
    nested_path.write_bytes(nested_payload)
    manifest_bytes = b'{"bundle":"fallback-test","version":1}'
    (staging_dir / MANIFEST_FILENAME).write_bytes(manifest_bytes)

    events: list[str] = []
    real_rmtree = bundle_module.shutil.rmtree
    real_write_bytes_exclusive = bundle_module._write_bytes_exclusive

    def record_rmtree(path: str | Path, *args: Any, **kwargs: Any) -> None:
        if Path(path) == staging_dir:
            events.append("staging-removed")
            assert not (destination_dir / MANIFEST_FILENAME).exists()
        real_rmtree(path, *args, **kwargs)

    def record_write_manifest(
        destination_path: Path, payload: bytes, created_files: list[Path]
    ) -> None:
        if destination_path.name == MANIFEST_FILENAME:
            events.append("manifest-written")
            assert not staging_dir.exists()
        real_write_bytes_exclusive(destination_path, payload, created_files)

    monkeypatch.setattr(bundle_module.shutil, "rmtree", record_rmtree)
    monkeypatch.setattr(bundle_module, "_write_bytes_exclusive", record_write_manifest)

    api["_publish_directory_no_replace_via_claim_then_populate"](staging_dir, destination_dir)

    assert events == ["staging-removed", "manifest-written"]
    assert (destination_dir / nested_relpath).read_bytes() == nested_payload
    assert (destination_dir / MANIFEST_FILENAME).read_bytes() == manifest_bytes
    assert not staging_dir.exists()


def test_ac11_fallback_claim_then_populate_refuses_preexisting_empty_destination(
    tmp_path: Path,
) -> None:
    api = _bundle_api()
    staging_dir = tmp_path / "staging"
    destination_dir = tmp_path / "final-run"
    staging_dir.mkdir()
    (staging_dir / "artifact.bin").write_bytes(b"payload")
    (staging_dir / MANIFEST_FILENAME).write_bytes(b'{"bundle":"fallback-test"}')
    destination_dir.mkdir()

    with pytest.raises(FileExistsError):
        api["_publish_directory_no_replace_via_claim_then_populate"](staging_dir, destination_dir)

    assert destination_dir.exists()
    assert list(destination_dir.iterdir()) == []
    assert (staging_dir / MANIFEST_FILENAME).is_file()


def test_ac11_fallback_staging_cleanup_failure_rolls_back_and_write_bundle_run_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _bundle_api()
    bundle_module = _load_module("raptor.external.tsc2_sources.bundle")
    manifest, payloads = _minimal_bundle_manifest_and_payload(run_tag="fallback-staging-cleanup")
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    output_root = tmp_path / "external-root"
    output_root.mkdir()
    run_name = "fallback-staging-cleanup-run"
    final_run_dir = output_root / run_name
    real_fallback_publish = api["_publish_directory_no_replace_via_claim_then_populate"]
    real_rmtree = bundle_module.shutil.rmtree
    injected_failure = {"triggered": False}

    def force_fallback_publish(staging_dir: str | Path, destination_dir: str | Path) -> None:
        real_fallback_publish(Path(staging_dir), Path(destination_dir))

    def fail_once_precommit_staging_cleanup(path: str | Path, *args: Any, **kwargs: Any) -> None:
        path_obj = Path(path)
        ignore_errors = bool(kwargs.get("ignore_errors"))
        if (
            not injected_failure["triggered"]
            and not ignore_errors
            and path_obj.name.startswith(f".{run_name}.staging-")
        ):
            injected_failure["triggered"] = True
            raise OSError("simulated fallback pre-commit staging cleanup failure")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(bundle_module, "_publish_directory_no_replace", force_fallback_publish)
    monkeypatch.setattr(bundle_module.shutil, "rmtree", fail_once_precommit_staging_cleanup)

    with pytest.raises(api["BundleBoundaryError"]):
        api["write_bundle_run"](
            repo_root=repo_root,
            output_root=output_root,
            run_name=run_name,
            manifest=manifest,
            artifact_payloads=payloads,
        )

    assert injected_failure["triggered"]
    assert not final_run_dir.exists()
    assert not (final_run_dir / MANIFEST_FILENAME).exists()
    assert not list(output_root.glob(f".{run_name}.staging-*"))


def test_ac11_fallback_cleanup_failure_never_reports_failure_with_committed_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _bundle_api()
    bundle_module = _load_module("raptor.external.tsc2_sources.bundle")
    manifest, payloads = _minimal_bundle_manifest_and_payload(run_tag="fallback-rollback-cleanup")
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    output_root = tmp_path / "external-root"
    output_root.mkdir()
    run_name = "fallback-rollback-cleanup-run"
    final_run_dir = output_root / run_name
    real_fallback_publish = api["_publish_directory_no_replace_via_claim_then_populate"]

    def force_fallback_publish(staging_dir: str | Path, destination_dir: str | Path) -> None:
        real_fallback_publish(Path(staging_dir), Path(destination_dir))

    def fail_non_manifest_copy(_src: Path, _dst: Path, _created_files: list[Path]) -> None:
        raise OSError("simulated non-manifest copy failure")

    def fail_rollback_cleanup(
        _destination_dir: Path,
        _created_dirs: list[Path],
        _created_files: list[Path],
    ) -> None:
        raise OSError("simulated rollback cleanup failure")

    monkeypatch.setattr(bundle_module, "_publish_directory_no_replace", force_fallback_publish)
    monkeypatch.setattr(bundle_module, "_copy_file_exclusive", fail_non_manifest_copy)
    monkeypatch.setattr(bundle_module, "_rollback_claimed_publication", fail_rollback_cleanup)

    with pytest.raises(api["BundleBoundaryError"]):
        api["write_bundle_run"](
            repo_root=repo_root,
            output_root=output_root,
            run_name=run_name,
            manifest=manifest,
            artifact_payloads=payloads,
        )

    assert not (final_run_dir / MANIFEST_FILENAME).exists()
    assert not list(output_root.glob(f".{run_name}.staging-*"))


def test_ac13_package_init_does_not_claim_implemented_modules_are_absent() -> None:
    init_path = PACKAGE_ROOT / "__init__.py"
    if not init_path.is_file():
        pytest.fail(f"TSC2 source package __init__ is missing: {init_path}")

    for module_name in ("mavedb.py", "igvf.py", "bundle.py", "ingest.py"):
        module_path = PACKAGE_ROOT / module_name
        assert module_path.is_file(), f"expected implemented module is missing: {module_path}"

    text = init_path.read_text(encoding="utf-8").lower()
    normalized = " ".join(text.split())
    assert "not present yet" not in normalized


def test_ac10_staged_igvf_release_state_does_not_promote_legacy_mave_registry() -> None:
    staged_config_path = REPO_ROOT / "configs" / "external" / "tsc2_source_ingestion_v1.yaml"
    staged_payload = yaml.safe_load(staged_config_path.read_text(encoding="utf-8"))
    staged_sources = staged_payload.get("sources")
    assert isinstance(staged_sources, dict)

    expected_staged = {
        "igvf_vamp_seq": {
            "analysis_set": "IGVFDS5595BTYJ",
            "file_accession": "IGVFFI9747KART",
            "required_status": "released",
            "required_controlled_access": False,
            "expected_assembly": "GRCh38",
            "expected_file_size": 439700,
            "expected_md5": "1a397944b7a5158b3d63999dfcf926db",
            "licence_state": "REVIEW_REQUIRED",
            "redistribution": "FORBIDDEN_UNTIL_REVIEW",
            "legacy_urn": "IGVF:analysis-set:IGVFDS5595BTYJ",
        },
        "igvf_sge": {
            "analysis_set": "IGVFDS1782FCXW",
            "file_accession": "IGVFFI3097DFGF",
            "required_status": "released",
            "required_controlled_access": False,
            "expected_assembly": "GRCh38",
            "expected_file_size": 35101,
            "expected_md5": "c188e0a9dd4c67dfac13381d3879aedf",
            "licence_state": "REVIEW_REQUIRED",
            "redistribution": "FORBIDDEN_UNTIL_REVIEW",
            "legacy_urn": "IGVF:analysis-set:IGVFDS1782FCXW",
        },
    }
    for source_id, expected in expected_staged.items():
        staged_source = staged_sources.get(source_id)
        assert isinstance(staged_source, dict), f"missing staged source: {source_id}"
        assert staged_source.get("analysis_set") == expected["analysis_set"]
        assert staged_source.get("file_accession") == expected["file_accession"]
        assert staged_source.get("required_status") == expected["required_status"]
        assert staged_source.get("required_controlled_access") is expected[
            "required_controlled_access"
        ]
        assert staged_source.get("expected_assembly") == expected["expected_assembly"]
        assert staged_source.get("expected_file_size") == expected["expected_file_size"]
        assert staged_source.get("expected_md5") == expected["expected_md5"]
        assert staged_source.get("licence_state") == expected["licence_state"]
        assert staged_source.get("redistribution") == expected["redistribution"]

    legacy_config_path = REPO_ROOT / "configs" / "external" / "mave_sources.yaml"
    legacy_payload = yaml.safe_load(legacy_config_path.read_text(encoding="utf-8"))
    legacy_sources = legacy_payload.get("sources")
    assert isinstance(legacy_sources, list)
    legacy_by_urn = {
        source.get("urn"): source
        for source in legacy_sources
        if isinstance(source, dict) and source.get("urn")
    }
    for expected in expected_staged.values():
        legacy_entry = legacy_by_urn.get(expected["legacy_urn"])
        assert isinstance(legacy_entry, dict), f"missing legacy source: {expected['legacy_urn']}"
        assert legacy_entry.get("verification") == "confirm_pending"


def test_ac14_aggregate_summary_schema_and_required_source_ids_are_validated_in_memory() -> None:
    api = _bundle_api()
    source_kind = {
        "pubmed": "pubmed",
        "litvar2": "litvar2",
        "pmc": "pmc",
        "mavedb_clipe": "mavedb",
        "igvf_vamp_seq": "igvf",
        "igvf_sge": "igvf",
    }

    artifacts: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for index, source_id in enumerate(REQUIRED_PILOT_SOURCE_IDS, start=1):
        body = f"summary-{source_id}".encode("utf-8")
        artifact_id = f"{source_id}-artifact"
        relative_path = f"{source_id}/artifact-{index}.bin"
        artifacts.append(
            _artifact_record(
                artifact_id=artifact_id,
                source_id=source_id,
                relative_path=relative_path,
                body=body,
            )
        )
        if source_id.startswith("igvf_"):
            lifecycle_state = "STAGED_LICENCE_REVIEW_REQUIRED"
            licence_state = "REVIEW_REQUIRED"
        else:
            lifecycle_state = "STAGED_VERIFIED"
            licence_state = "EXPLICIT_LICENSE_DECLARED"
        sources.append(
            _source_record(
                source_id=source_id,
                source_kind=source_kind[source_id],
                artifact_ids=[artifact_id],
                lifecycle_state=lifecycle_state,
                licence_state=licence_state,
            )
        )
        sources[-1]["observations"] = {"source_count": index}

    manifest = api["build_bundle_manifest"](
        bundle_id="tsc2-source-pilot-2026-09-09",
        created_at="2026-09-09T00:00:00Z",
        query={"gene": "TSC2"},
        artifacts=artifacts,
        sources=sources,
        truncation={"pubmed": {"count": 3, "returned_count": 2, "is_truncated": True}},
        boundaries={"network": "injected", "external_output_only": True},
    )
    summary = api["build_pilot_summary"](manifest)
    source_ids = [source["source_id"] for source in sources]

    assert summary["schema"] == "raptor.external.tsc2_source_pilot_summary.v1"
    assert set(summary) == {
        "schema",
        "bundle_id",
        "manifest_content_hash",
        "counts",
        "source_ids",
        "missing_source_ids",
        "truncation",
        "source_states",
        "source_observations",
        "artifact_integrity",
        "normalization_gaps",
    }
    assert "artifact_hashes" not in summary
    assert summary["bundle_id"] == manifest["bundle_id"]
    assert summary["manifest_content_hash"] == manifest["content_hash"]
    assert summary["counts"] == {"sources": 6, "artifacts": 6}
    assert summary["source_ids"] == source_ids
    assert summary["missing_source_ids"] == []
    assert summary["truncation"] == manifest["truncation"]
    assert summary["source_states"] == {
        source["source_id"]: {
            "source_kind": source["source_kind"],
            "lifecycle_state": source["lifecycle_state"],
            "access_state": source["access_state"],
            "licence_state": source["licence_state"],
        }
        for source in sources
    }
    assert summary["source_observations"] == {
        source["source_id"]: source["observations"] for source in sources
    }
    assert summary["artifact_integrity"] == _artifact_integrity_map(artifacts)


def test_ac14_generated_pilot_summary_file_matches_v1_0_5_contract_if_present() -> None:
    summary_path = (
        REPO_ROOT / "data" / "census" / "tsc2_source_ingestion_pilot_2026-09-09.json"
    )
    if not summary_path.is_file():
        pytest.skip(f"pilot summary file is absent: {summary_path}")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert set(summary) == {
        "schema",
        "bundle_id",
        "manifest_content_hash",
        "counts",
        "source_ids",
        "missing_source_ids",
        "truncation",
        "source_states",
        "source_observations",
        "artifact_integrity",
        "normalization_gaps",
    }
    assert "artifact_hashes" not in summary
    assert summary["schema"] == "raptor.external.tsc2_source_pilot_summary.v1"
    assert summary["bundle_id"] == "tsc2-source-pilot-2026-09-09"
    assert (
        summary["manifest_content_hash"]
        == "63bd6eb4e7182b7f2d345cd78b3a110a59c361c72d521b88990c475919865808"
    )
    assert summary["source_ids"] == REQUIRED_PILOT_SOURCE_IDS
    assert summary["missing_source_ids"] == []
    assert summary["counts"] == {"sources": 6, "artifacts": 12}
    assert summary["truncation"] == {
        "pubmed": {"count": 189, "returned_count": 100, "is_truncated": True}
    }

    source_states = summary["source_states"]
    assert isinstance(source_states, dict)
    assert set(source_states) == set(REQUIRED_PILOT_SOURCE_IDS)

    source_observations = summary["source_observations"]
    assert isinstance(source_observations, dict)
    assert set(source_observations) == set(REQUIRED_PILOT_SOURCE_IDS)
    assert source_observations["pubmed"]["count"] == 189
    assert source_observations["pubmed"]["returned_count"] == 100
    assert source_observations["litvar2"]["mapping_count"] == 3946
    assert source_observations["litvar2"]["rsid_mapping_count"] == 2902
    assert source_observations["litvar2"]["rsidless_mapping_count"] == 1044
    assert source_observations["mavedb_clipe"]["variant_count"] == 208
    assert source_observations["igvf_vamp_seq"]["status"] == "released"
    assert source_observations["igvf_vamp_seq"]["assembly"] == "GRCh38"
    assert source_observations["igvf_vamp_seq"]["byte_length"] == 439700
    assert source_observations["igvf_sge"]["status"] == "released"
    assert source_observations["igvf_sge"]["assembly"] == "GRCh38"
    assert source_observations["igvf_sge"]["byte_length"] == 35101

    artifact_integrity = summary["artifact_integrity"]
    assert isinstance(artifact_integrity, dict)
    assert len(artifact_integrity) == 12
    assert len(set(artifact_integrity)) == 12
    assert artifact_integrity["igvf_vamp_seq-download-tsv-gz"]["md5"] == "1a397944b7a5158b3d63999dfcf926db"
    assert artifact_integrity["igvf_vamp_seq-download-tsv-gz"]["byte_length"] == 439700
    assert artifact_integrity["igvf_sge-download-tsv-gz"]["md5"] == "c188e0a9dd4c67dfac13381d3879aedf"
    assert artifact_integrity["igvf_sge-download-tsv-gz"]["byte_length"] == 35101
    assert (
        artifact_integrity["mavedb_clipe-scores-csv"]["sha256"]
        == "74fef301d3b3cf6b6958161f7eaf8fa1ebab7ae35befae3879d0a9841c769717"
    )
    for entry in artifact_integrity.values():
        assert set(entry) == {"sha256", "md5", "byte_length", "verification"}
        _assert_hex_digest(entry["sha256"], length=64)
        _assert_hex_digest(entry["md5"], length=32)
        assert isinstance(entry["byte_length"], int)
        assert entry["byte_length"] > 0
        assert isinstance(entry["verification"], str)
        assert entry["verification"]

    blob = json.dumps(summary, sort_keys=True).lower()
    forbidden_payload_tokens = (
        "requested_url",
        "final_url",
        "full_text",
        "abstract_text",
        "variant_id",
        "hgvs",
        "patient",
        "api_key",
        "awsaccesskeyid",
        "x-amz-signature",
        "classification",
        "pathogenic",
        "benign",
        "ps3",
        "bs3",
    )
    assert not any(token in blob for token in forbidden_payload_tokens)
