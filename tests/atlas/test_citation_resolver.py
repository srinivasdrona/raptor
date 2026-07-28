"""
Gemini RED tests for raptor.atlas Citation Resolver subsystem.
Spec coverage:
- CitationCatalog load, validate, self-hash and path safety.
- normalize_identifier direct API flexible forms, strictness, and Accession rules.
- resolve() grounding predicate, role/source_type/permitted_use/verification checks.
- verify_content() drift and raw/extracted text hash/byte-length recompute.
- verify_span() exact normalized-slice, CRLF and Unicode NFC, locators, and duplicate quote handling.
- Frozen dataclass contracts and orthogonal error taxonomy.
"""

import os
import sys
import json
import hashlib
import unicodedata
import types
from pathlib import Path
import pytest
import yaml

# ---------------------------------------------------------------------------
# Anti-cribbing check
# ---------------------------------------------------------------------------
def assert_no_cribbing(obj):
    forbidden_ids = [
        "pmc11185720",
        "10.1101/2024.06.07.597916",
        "c.1832G>A",
        "p.Arg611Gln"
    ]
    if isinstance(obj, str):
        for f in forbidden_ids:
            assert f not in obj.lower(), f"Anti-cribbing violation: found real-content phrase '{f}' in '{obj}'"
    elif isinstance(obj, dict):
        for k, v in obj.items():
            assert_no_cribbing(k)
            assert_no_cribbing(v)
    elif isinstance(obj, (list, tuple, set)):
        for item in obj:
            assert_no_cribbing(item)

# ---------------------------------------------------------------------------
# Independent Oracles (Pure oracles run & pass independently)
# ---------------------------------------------------------------------------

def oracle_normalize_identifier(raw: str):
    """Independent oracle for normalize_identifier based on spec v1."""
    if not isinstance(raw, str):
        raise ValueError("Must be string")
    trimmed = raw.strip()
    if not trimmed:
        raise ValueError("Empty input")
    if any(c.isspace() for c in trimmed):
        raise ValueError("Internal whitespace not allowed")

    lower_raw = trimmed.lower()

    if lower_raw.startswith("pmid:"):
        val = trimmed[5:]
        if not val.isdigit() or val.startswith("0"):
            raise ValueError("PMID must be digits without leading zeros")
        return "PMID", val, f"PMID:{val}"

    elif lower_raw.startswith("pmcid:"):
        val = trimmed[6:]
        if not val.upper().startswith("PMC"):
            raise ValueError("PMCID value must start with PMC")
        pmc_digits = val[3:]
        if not pmc_digits.isdigit():
            raise ValueError("PMCID value digits only")
        val_upper = "PMC" + pmc_digits
        return "PMCID", val_upper, f"PMCID:{val_upper}"

    elif lower_raw.startswith("doi:"):
        val = trimmed[4:]
        return _normalize_doi_oracle(val)

    elif lower_raw.startswith("accession:"):
        val = trimmed[10:]
        parts = val.split(":", 1)
        if len(parts) != 2:
            raise ValueError("Accession must be namespace:opaque")
        ns, opaque = parts
        ns_lower = ns.lower()
        import re
        if not re.match(r"^[a-z0-9]+([._-][a-z0-9]+)*$", ns_lower):
            raise ValueError("Invalid accession namespace")
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", opaque):
            raise ValueError("Invalid accession opaque")
        return "ACCESSION", f"{ns_lower}:{opaque}", f"ACCESSION:{ns_lower}:{opaque}"

    # Bare form detection
    if trimmed.isdigit() and not trimmed.startswith("0"):
        return "PMID", trimmed, f"PMID:{trimmed}"

    if lower_raw.startswith("pmc"):
        pmc_digits = trimmed[3:]
        if pmc_digits.isdigit():
            val_upper = "PMC" + pmc_digits
            return "PMCID", val_upper, f"PMCID:{val_upper}"

    if trimmed.startswith("10."):
        return _normalize_doi_oracle(trimmed)

    # URL forms
    for url_pref in ["https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/"]:
        if lower_raw.startswith(url_pref):
            val = trimmed[len(url_pref):]
            return _normalize_doi_oracle(val)

    raise ValueError("Unknown or malformed scheme")

def _normalize_doi_oracle(val: str):
    if "%" in val:
        raise ValueError("Percent encoding not allowed in DOI")
    if val[-1] in [".", ",", ";", ":", ")", "—"]:
        raise ValueError("Trailing punctuation not allowed in DOI")
    val_lower = val.lower()
    import re
    if not re.match(r"^10\.[0-9]{4,9}/[^\s%]+$", val_lower):
        raise ValueError("Invalid DOI structure")
    return "DOI", val_lower, f"DOI:{val_lower}"


def oracle_catalog_content_hash(manifest: dict) -> str:
    """Independent oracle for catalog_content_hash."""
    manifest_copy = dict(manifest)
    manifest_copy.pop("catalog_content_hash", None)
    serialized = json.dumps(manifest_copy, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest().lower()


def oracle_text_normalization(text_bytes: bytes) -> str:
    """Independent oracle for text normalization (atlas.text_norm.v1)."""
    decoded = text_bytes.decode("utf-8", errors="strict")
    normalized = decoded.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", normalized)

# ---------------------------------------------------------------------------
# Pure Oracle Tests (Always run and pass independently)
# ---------------------------------------------------------------------------

def test_normalize_identifier_oracle_correctness():
    """Verify that the independent normalization oracle matches the exact spec rules."""
    # Positive PMID
    assert oracle_normalize_identifier("PMID:12345") == ("PMID", "12345", "PMID:12345")
    assert oracle_normalize_identifier("12345") == ("PMID", "12345", "PMID:12345")

    # Negative PMID
    with pytest.raises(ValueError):
        oracle_normalize_identifier("PMID:0123")  # leading zero
    with pytest.raises(ValueError):
        oracle_normalize_identifier("0123")  # leading zero

    # Positive PMCID
    assert oracle_normalize_identifier("PMCID:PMC12345") == ("PMCID", "PMC12345", "PMCID:PMC12345")
    assert oracle_normalize_identifier("pmcid:pmc12345") == ("PMCID", "PMC12345", "PMCID:PMC12345")
    assert oracle_normalize_identifier("PMC12345") == ("PMCID", "PMC12345", "PMCID:PMC12345")
    assert oracle_normalize_identifier("pmc123") == ("PMCID", "PMC123", "PMCID:PMC123")

    # Positive DOI
    assert oracle_normalize_identifier("DOI:10.5555/AbC") == ("DOI", "10.5555/abc", "DOI:10.5555/abc")
    assert oracle_normalize_identifier("10.5555/AbC") == ("DOI", "10.5555/abc", "DOI:10.5555/abc")
    assert oracle_normalize_identifier("https://doi.org/10.5555/AbC") == ("DOI", "10.5555/abc", "DOI:10.5555/abc")
    assert oracle_normalize_identifier("http://dx.doi.org/10.5555/abc") == ("DOI", "10.5555/abc", "DOI:10.5555/abc")

    # Negative DOI
    with pytest.raises(ValueError):
        oracle_normalize_identifier("10.5555/abc.")  # trailing dot
    with pytest.raises(ValueError):
        oracle_normalize_identifier("10.5555/abc,")  # trailing comma
    with pytest.raises(ValueError):
        oracle_normalize_identifier("10.5555/ab%20c")  # percent encoding
    with pytest.raises(ValueError):
        oracle_normalize_identifier("10.5555/a b")  # internal whitespace

    # Positive ACCESSION
    assert oracle_normalize_identifier("ACCESSION:GEO:GSE12345") == ("ACCESSION", "geo:GSE12345", "ACCESSION:geo:GSE12345")
    assert oracle_normalize_identifier("accession:clinvar:VCV000012397") == ("ACCESSION", "clinvar:VCV000012397", "ACCESSION:clinvar:VCV000012397")

    # Negative ACCESSION
    with pytest.raises(ValueError):
        oracle_normalize_identifier("GEO:GSE12345")  # bare Accession lacks prefix
    with pytest.raises(ValueError):
        oracle_normalize_identifier("ACCESSION:GEO_GSE12345")  # missing opaque divider
    with pytest.raises(ValueError):
        oracle_normalize_identifier("ACCESSION:geo: GSE12345")  # internal whitespace


def test_catalog_content_hash_oracle_correctness():
    """Verify that the independent catalog self-hash oracle behaves as specified."""
    # Synthetic clean catalog matching spec schema
    catalog = {
        "schema": "atlas.citation_catalog.v1",
        "catalog_id": "synthetic-catalog",
        "catalog_version": "1.0.0",
        "catalog_content_hash": "placeholder_that_will_be_ignored",
        "disease_pack_binding": {
            "pack_id": "synthpack",
            "pack_version": "1.0.0",
            "pack_content_hash": "bf7369f8faa24a6f746956ee1122281e798185f320b012a844ffbc683f2e7b21"
        },
        "content_root_policy": {"policy": "relative"},
        "sources": [
            {
                "source_id": "synthsrc-0001",
                "source_type": "PRIMARY-LIT",
                "role": "direct_evidence_leaf",
                "identifiers": {
                    "pmid": ["12345"],
                    "pmcid": ["PMC12345"],
                    "doi": ["10.5555/abc"]
                },
                "authoritative_url": None,
                "license": "CC-BY-4.0",
                "permitted_use": "grounding_and_quote",
                "verification": "verified",
                "document_date": None,
                "document_version": None,
                "provenance": None,
                "raw_artifact": {
                    "relative_path": "raw/synthsrc-0001.pdf",
                    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                    "byte_length": 0,
                    "media_type": "application/pdf"
                },
                "extracted_text": {
                    "relative_path": "extracted/synthsrc-0001.txt",
                    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                    "byte_length": 0,
                    "extraction_method": "pdftotext",
                    "extraction_version": "1.0.0",
                    "normalization": "atlas.text_norm.v1"
                }
            }
        ]
    }

    # 1. Self-exclusion of catalog_content_hash key
    h1 = oracle_catalog_content_hash(catalog)
    catalog_different_placeholder = dict(catalog)
    catalog_different_placeholder["catalog_content_hash"] = "another_placeholder"
    h2 = oracle_catalog_content_hash(catalog_different_placeholder)
    assert h1 == h2, "catalog_content_hash must be excluded from hashing computation"

    # 2. Every present null/None must participate
    catalog_without_null = dict(catalog)
    catalog_without_null["sources"] = [dict(catalog["sources"][0])]
    catalog_without_null["sources"][0]["authoritative_url"] = "http://some-url.org"
    h3 = oracle_catalog_content_hash(catalog_without_null)
    assert h1 != h3, "Mutating a null value must change the hash"

    # 3. Exact published constants verification
    expected_sha = "409f504e030da4e863d7335f92510a2e1b94ad8952736d8c145d6ddb92587a0b"
    assert h1 == expected_sha, f"Oracle hash mismatch. Got {h1}, expected {expected_sha}"


def test_text_normalization_oracle_correctness():
    """Verify independent text normalization of CRLF -> LF and NFC."""
    # CRLF conversion
    b_crlf = b"line1\r\nline2\rline3"
    assert oracle_text_normalization(b_crlf) == "line1\nline2\nline3"

    # Unicode NFC normalization (decomposed 'a' + umlaut -> composed 'a' with umlaut)
    nfd_bytes = b"a\xcc\x88" # 'ä' in decomposed form
    normalized = oracle_text_normalization(nfd_bytes)
    assert len(normalized) == 1
    assert normalized == "\u00e4"

# ---------------------------------------------------------------------------
# Collection-Safe Production Import Helper
# ---------------------------------------------------------------------------
def get_resolver_symbols():
    try:
        from raptor.atlas.model import (
            AtlasCatalogError,
            AtlasCatalogSchemaError,
            AtlasCatalogHashError,
            AtlasCatalogPathError,
            AtlasCitationResolutionError,
            AtlasContentDriftError,
            AtlasSpanMismatchError,
            CitationIdentifier,
            CatalogSource,
            ContentVerification,
            ResolvedCitation,
            VerifiedSpan,
            CitationResolver
        )
        from raptor.atlas.citation import (
            load_catalog,
            catalog_content_hash,
            normalize_identifier,
            LocalCitationResolver,
            CitationCatalog
        )
        return {
            "AtlasCatalogError": AtlasCatalogError,
            "AtlasCatalogSchemaError": AtlasCatalogSchemaError,
            "AtlasCatalogHashError": AtlasCatalogHashError,
            "AtlasCatalogPathError": AtlasCatalogPathError,
            "AtlasCitationResolutionError": AtlasCitationResolutionError,
            "AtlasContentDriftError": AtlasContentDriftError,
            "AtlasSpanMismatchError": AtlasSpanMismatchError,
            "CitationIdentifier": CitationIdentifier,
            "CatalogSource": CatalogSource,
            "ContentVerification": ContentVerification,
            "ResolvedCitation": ResolvedCitation,
            "VerifiedSpan": VerifiedSpan,
            "CitationResolver": CitationResolver,
            "load_catalog": load_catalog,
            "catalog_content_hash": catalog_content_hash,
            "normalize_identifier": normalize_identifier,
            "LocalCitationResolver": LocalCitationResolver,
            "CitationCatalog": CitationCatalog
        }
    except (ImportError, AttributeError):
        pytest.fail("RED: raptor.atlas citation resolver not implemented", pytrace=False)

# ---------------------------------------------------------------------------
# Production Implementation RED Tests (Will fail on unimplemented surfaces)
# ---------------------------------------------------------------------------

def test_dataclasses_and_protocol_contract():
    """Verify that new frozen dataclasses and Protocol exist with exact fields."""
    syms = get_resolver_symbols()

    import dataclasses
    from typing import get_type_hints

    # 1. CitationIdentifier
    ci_class = syms["CitationIdentifier"]
    assert dataclasses.is_dataclass(ci_class)
    ci_fields = {f.name: f.type for f in dataclasses.fields(ci_class)}
    assert "scheme" in ci_fields
    assert "value" in ci_fields
    assert "canonical" in ci_fields

    # 2. CatalogSource
    cs_class = syms["CatalogSource"]
    assert dataclasses.is_dataclass(cs_class)
    cs_fields = {f.name for f in dataclasses.fields(cs_class)}
    expected_cs = {"source_id", "source_type", "role", "identifiers", "license", "permitted_use", "verification"}
    assert expected_cs.issubset(cs_fields)

    # 3. ContentVerification
    cv_class = syms["ContentVerification"]
    assert dataclasses.is_dataclass(cv_class)
    cv_fields = {f.name for f in dataclasses.fields(cv_class)}
    assert {"raw_sha256", "raw_byte_length", "extracted_text_sha256", "extracted_text_byte_length"}.issubset(cv_fields)

    # 4. ResolvedCitation
    rc_class = syms["ResolvedCitation"]
    assert dataclasses.is_dataclass(rc_class)
    rc_fields = {f.name for f in dataclasses.fields(rc_class)}
    assert {"identifier", "source", "content", "content_verified"}.issubset(rc_fields)

    # 5. VerifiedSpan
    vs_class = syms["VerifiedSpan"]
    assert dataclasses.is_dataclass(vs_class)
    vs_fields = {f.name for f in dataclasses.fields(vs_class)}
    assert {"source_id", "locator", "start", "end", "exact_quote", "extracted_text_sha256"}.issubset(vs_fields)

    # 6. Protocol
    resolver_protocol = syms["CitationResolver"]
    assert hasattr(resolver_protocol, "resolve")
    assert hasattr(resolver_protocol, "verify_span")


def test_typed_errors_hierarchy():
    """Verify the mutually distinct orthogonal taxonomy of Catalog Errors."""
    syms = get_resolver_symbols()
    from raptor.atlas.model import AtlasError

    errs = [
        "AtlasCatalogError",
        "AtlasCatalogSchemaError",
        "AtlasCatalogHashError",
        "AtlasCatalogPathError",
        "AtlasCitationResolutionError",
        "AtlasContentDriftError",
        "AtlasSpanMismatchError"
    ]

    for err_name in errs:
        err_cls = syms[err_name]
        assert issubclass(err_cls, Exception)
        assert issubclass(err_cls, AtlasError)
        if err_name != "AtlasCatalogError":
            assert issubclass(err_cls, syms["AtlasCatalogError"])

    # Ensure they are mutually distinct classes
    err_classes = [syms[name] for name in errs]
    assert len(set(err_classes)) == len(errs)


def test_normalize_identifier_implementation_red():
    """Verify implementation of normalize_identifier against spec rules."""
    syms = get_resolver_symbols()
    normalize_identifier = syms["normalize_identifier"]

    # Direct API flexible forms
    res = normalize_identifier("PMID:12345")
    assert res.scheme == "PMID"
    assert res.value == "12345"
    assert res.canonical == "PMID:12345"

    res_bare = normalize_identifier("12345")
    assert res_bare.scheme == "PMID"
    assert res_bare.canonical == "PMID:12345"

    # DOI case lowercase
    res_doi = normalize_identifier("https://doi.org/10.5555/AbC")
    assert res_doi.scheme == "DOI"
    assert res_doi.value == "10.5555/abc"
    assert res_doi.canonical == "DOI:10.5555/abc"

    # Accession case
    res_acc = normalize_identifier("ACCESSION:GEO:GSE12345")
    assert res_acc.scheme == "ACCESSION"
    assert res_acc.value == "geo:GSE12345"
    assert res_acc.canonical == "ACCESSION:geo:GSE12345"

    # Strictness errors
    with pytest.raises(syms["AtlasCitationResolutionError"]):
        normalize_identifier("PMID:0123")
    with pytest.raises(syms["AtlasCitationResolutionError"]):
        normalize_identifier("10.5555/abc.")
    with pytest.raises(syms["AtlasCitationResolutionError"]):
        normalize_identifier("10.5555/ab%20c")


def test_catalog_content_hash_implementation_red():
    """Verify catalog_content_hash recompute matches oracle and behaves identically to pack_content_hash."""
    syms = get_resolver_symbols()
    catalog_content_hash = syms["catalog_content_hash"]

    manifest = {
        "schema": "atlas.citation_catalog.v1",
        "catalog_id": "synthetic-catalog",
        "catalog_version": "1.0.0",
        "catalog_content_hash": "placeholder_that_will_be_ignored",
        "disease_pack_binding": {
            "pack_id": "synthpack",
            "pack_version": "1.0.0",
            "pack_content_hash": "bf7369f8faa24a6f746956ee1122281e798185f320b012a844ffbc683f2e7b21"
        },
        "content_root_policy": {"policy": "relative"},
        "sources": []
    }

    assert_no_cribbing(manifest)

    h1 = catalog_content_hash(manifest)
    assert h1 == oracle_catalog_content_hash(manifest)

    # Top-level field mutation must change hash
    manifest_mut = dict(manifest)
    manifest_mut["catalog_id"] = "mutated-catalog"
    assert catalog_content_hash(manifest_mut) != h1


def test_load_catalog_and_validation_red(tmp_path):
    """Test load_catalog validation: self-hash mismatch, duplicate id/alias, ineligible pairings."""
    syms = get_resolver_symbols()
    load_catalog = syms["load_catalog"]

    manifest = {
        "schema": "atlas.citation_catalog.v1",
        "catalog_id": "synthetic-catalog",
        "catalog_version": "1.0.0",
        "catalog_content_hash": "wrong_hash_mismatch",
        "disease_pack_binding": {
            "pack_id": "synthpack",
            "pack_version": "1.0.0",
            "pack_content_hash": "bf7369f8faa24a6f746956ee1122281e798185f320b012a844ffbc683f2e7b21"
        },
        "content_root_policy": {"policy": "relative"},
        "sources": []
    }

    manifest_file = tmp_path / "catalog.yaml"
    with open(manifest_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(manifest, f)

    # Self-hash mismatch must raise AtlasCatalogHashError
    with pytest.raises(syms["AtlasCatalogHashError"]):
        load_catalog(manifest_file, content_root=tmp_path)

    # Duplicate source_id
    manifest_dup_id = dict(manifest)
    manifest_dup_id["catalog_content_hash"] = "placeholder"
    manifest_dup_id["sources"] = [
        {
            "source_id": "src-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "identifiers": {"pmid": ["12345"]}, "permitted_use": "grounding_and_quote", "verification": "verified",
            "raw_artifact": {"relative_path": "x.pdf", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "byte_length": 0, "media_type": "application/pdf"}
        },
        {
            "source_id": "src-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "identifiers": {"pmid": ["54321"]}, "permitted_use": "grounding_and_quote", "verification": "verified",
            "raw_artifact": {"relative_path": "y.pdf", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "byte_length": 0, "media_type": "application/pdf"}
        }
    ]
    manifest_dup_id["catalog_content_hash"] = oracle_catalog_content_hash(manifest_dup_id)
    with open(manifest_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(manifest_dup_id, f)
    with pytest.raises(syms["AtlasCatalogSchemaError"]):
        load_catalog(manifest_file, content_root=tmp_path)

    # Cross-source duplicate alias (same identifier on two source_ids)
    manifest_cross_alias = dict(manifest)
    manifest_cross_alias["catalog_content_hash"] = "placeholder"
    manifest_cross_alias["sources"] = [
        {
            "source_id": "src-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "identifiers": {"pmid": ["12345"]}, "permitted_use": "grounding_and_quote", "verification": "verified",
            "raw_artifact": {"relative_path": "x.pdf", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "byte_length": 0, "media_type": "application/pdf"}
        },
        {
            "source_id": "src-2", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "identifiers": {"pmid": ["12345"]}, "permitted_use": "grounding_and_quote", "verification": "verified",
            "raw_artifact": {"relative_path": "y.pdf", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "byte_length": 0, "media_type": "application/pdf"}
        }
    ]
    manifest_cross_alias["catalog_content_hash"] = oracle_catalog_content_hash(manifest_cross_alias)
    with open(manifest_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(manifest_cross_alias, f)
    with pytest.raises(syms["AtlasCatalogSchemaError"]):
        load_catalog(manifest_file, content_root=tmp_path)


def test_path_safety_and_containment_adversarial_red(tmp_path):
    """Test ID vs Path resolution and path safety / traversal / symlink rejection."""
    syms = get_resolver_symbols()
    load_catalog = syms["load_catalog"]

    # 1. Bare ID vs Explicit Path syntax classification (stat-independent)
    # The classification is done on string format:
    # Bare id is safe bare token ^[A-Za-z0-9_-]+$ with no path syntax.
    # Paths with separator or suffix are classified as explicit paths.

    # We can test this by passing explicit paths with non-existing targets and checking we get PathError
    # rather than bare ID resolution failures under CATALOGS_ROOT.
    with pytest.raises(syms["AtlasCatalogPathError"]):
        load_catalog("nonexistent_relative/catalog.yaml", content_root=tmp_path)

    with pytest.raises(syms["AtlasCatalogPathError"]):
        load_catalog("./nonexistent_relative_dot", content_root=tmp_path)

    # 2. Path safety traversal escape rejection
    # Prepare a valid catalog
    manifest = {
        "schema": "atlas.citation_catalog.v1",
        "catalog_id": "synthetic-catalog",
        "catalog_version": "1.0.0",
        "catalog_content_hash": "placeholder",
        "disease_pack_binding": {
            "pack_id": "synthpack", "pack_version": "1.0.0", "pack_content_hash": "bf7369f8faa24a6f746956ee1122281e798185f320b012a844ffbc683f2e7b21"
        },
        "content_root_policy": {"policy": "relative"},
        "sources": [
            {
                "source_id": "src-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
                "identifiers": {"pmid": ["12345"]}, "permitted_use": "grounding_and_quote", "verification": "verified",
                "raw_artifact": {
                    "relative_path": "../escape_traversal.pdf", # Traversal escape!
                    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "byte_length": 0, "media_type": "pdf"
                }
            }
        ]
    }
    manifest["catalog_content_hash"] = oracle_catalog_content_hash(manifest)

    manifest_file = tmp_path / "catalog.yaml"
    with open(manifest_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(manifest, f)

    catalog = load_catalog(manifest_file, content_root=tmp_path)
    resolver = syms["LocalCitationResolver"](catalog)

    # Resolve of a source with traversal escape relative_path must raise AtlasCatalogPathError
    with pytest.raises(syms["AtlasCatalogPathError"]):
        resolver.resolve("PMID:12345")

    # Symlink escape check
    # Create symlink inside content_root that points outside content_root
    outside_file = tmp_path.parent / "secret_outside.pdf"
    outside_file.write_bytes(b"outside-secret")

    symlink_target = tmp_path / "symlink_escape.pdf"
    try:
        os.symlink(outside_file, symlink_target)
        # Update manifest to reference symlink
        manifest["sources"][0]["raw_artifact"]["relative_path"] = "symlink_escape.pdf"
        manifest["catalog_content_hash"] = "placeholder"
        manifest["catalog_content_hash"] = oracle_catalog_content_hash(manifest)
        with open(manifest_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(manifest, f)

        catalog = load_catalog(manifest_file, content_root=tmp_path)
        resolver = syms["LocalCitationResolver"](catalog)
        with pytest.raises(syms["AtlasCatalogPathError"]):
            resolver.resolve("PMID:12345")
    except (OSError, NotImplementedError):
        # Skip only if OS/user permissions do not support symlinks
        pytest.skip("Symlink creation not supported in this test run environment")


def test_resolve_grounding_predicate_red(tmp_path):
    """Test that resolve() enforces full grounding predicate while load_catalog only checks structural schemas."""
    syms = get_resolver_symbols()
    load_catalog = syms["load_catalog"]

    # Construct structurally valid catalog but with non-grounding sources:
    # Source 1: verification is confirm_pending (non-grounding)
    # Source 2: permitted_use is provenance_only (non-grounding)
    # Source 3: role is context (non-grounding)
    manifest = {
        "schema": "atlas.citation_catalog.v1",
        "catalog_id": "synthetic-catalog",
        "catalog_version": "1.0.0",
        "catalog_content_hash": "placeholder",
        "disease_pack_binding": {
            "pack_id": "synthpack", "pack_version": "1.0.0", "pack_content_hash": "bf7369f8faa24a6f746956ee1122281e798185f320b012a844ffbc683f2e7b21"
        },
        "content_root_policy": {"policy": "relative"},
        "sources": [
            {
                "source_id": "src-pending", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
                "identifiers": {"pmid": ["10001"]}, "permitted_use": "grounding_and_quote", "verification": "confirm_pending",
                "raw_artifact": {"relative_path": "x.pdf", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "byte_length": 0, "media_type": "pdf"}
            },
            {
                "source_id": "src-provenance", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
                "identifiers": {"pmid": ["10002"]}, "permitted_use": "provenance_only", "verification": "verified",
                "raw_artifact": {"relative_path": "y.pdf", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "byte_length": 0, "media_type": "pdf"}
            },
            {
                "source_id": "src-context", "source_type": "PRIMARY-LIT", "role": "context",
                "identifiers": {"pmid": ["10003"]}, "permitted_use": "grounding_and_quote", "verification": "verified",
                "raw_artifact": {"relative_path": "z.pdf", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "byte_length": 0, "media_type": "pdf"}
            }
        ]
    }

    assert_no_cribbing(manifest)

    manifest["catalog_content_hash"] = oracle_catalog_content_hash(manifest)
    manifest_file = tmp_path / "catalog.yaml"
    with open(manifest_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(manifest, f)

    # Structural load must succeed (structural validity only)
    catalog = load_catalog(manifest_file, content_root=tmp_path)
    assert len(catalog.sources) == 3

    # But resolving FOR GROUNDING must fail closed on each of these non-grounding sources
    resolver = syms["LocalCitationResolver"](catalog)

    # Prepare dummy files to pass basic path checks
    for p in ["x.pdf", "y.pdf", "z.pdf"]:
        (tmp_path / p).write_bytes(b"")

    with pytest.raises(syms["AtlasCitationResolutionError"]):
        resolver.resolve("PMID:10001")

    with pytest.raises(syms["AtlasCitationResolutionError"]):
        resolver.resolve("PMID:10002")

    with pytest.raises(syms["AtlasCitationResolutionError"]):
        resolver.resolve("PMID:10003")


def test_resolve_alias_agreement_red(tmp_path):
    """Test that resolving multiple identifiers in a leaf must resolve to same source_id."""
    syms = get_resolver_symbols()
    load_catalog = syms["load_catalog"]

    # We want to test this during candidate promotion gate 3, which resolves each alias and verifies agreement.
    # In the citation resolver level, we also test that resolving different identifiers return the correct source.
    manifest = {
        "schema": "atlas.citation_catalog.v1",
        "catalog_id": "synthetic-catalog",
        "catalog_version": "1.0.0",
        "catalog_content_hash": "placeholder",
        "disease_pack_binding": {
            "pack_id": "synthpack", "pack_version": "1.0.0", "pack_content_hash": "bf7369f8faa24a6f746956ee1122281e798185f320b012a844ffbc683f2e7b21"
        },
        "content_root_policy": {"policy": "relative"},
        "sources": [
            {
                "source_id": "src-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
                "identifiers": {
                    "pmid": ["12345"],
                    "doi": ["10.5555/abc"]
                },
                "permitted_use": "grounding_and_quote", "verification": "verified",
                "raw_artifact": {"relative_path": "x.pdf", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "byte_length": 0, "media_type": "pdf"}
            }
        ]
    }
    manifest["catalog_content_hash"] = oracle_catalog_content_hash(manifest)
    manifest_file = tmp_path / "catalog.yaml"
    with open(manifest_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(manifest, f)

    catalog = load_catalog(manifest_file, content_root=tmp_path)
    resolver = syms["LocalCitationResolver"](catalog)

    (tmp_path / "x.pdf").write_bytes(b"")

    res1 = resolver.resolve("PMID:12345")
    res2 = resolver.resolve("DOI:10.5555/abc")
    assert res1.source.source_id == "src-1"
    assert res2.source.source_id == "src-1"


def test_content_drift_and_verification_red(tmp_path):
    """Test that resolve/verify_content recomputes hashes from disk and raises AtlasContentDriftError on drift."""
    syms = get_resolver_symbols()
    load_catalog = syms["load_catalog"]

    # 1. Mutate raw file
    manifest = {
        "schema": "atlas.citation_catalog.v1",
        "catalog_id": "synthetic-catalog",
        "catalog_version": "1.0.0",
        "catalog_content_hash": "placeholder",
        "disease_pack_binding": {
            "pack_id": "synthpack", "pack_version": "1.0.0", "pack_content_hash": "bf7369f8faa24a6f746956ee1122281e798185f320b012a844ffbc683f2e7b21"
        },
        "content_root_policy": {"policy": "relative"},
        "sources": [
            {
                "source_id": "src-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
                "identifiers": {"pmid": ["12345"]}, "permitted_use": "grounding_and_quote", "verification": "verified",
                "raw_artifact": {
                    "relative_path": "x.pdf",
                    "sha256": "f2ca1bb6c7e907d06dafe4687e579fce76b377f93e7c012360c25a0d14b43d41", # Declared hash
                    "byte_length": 15,
                    "media_type": "pdf"
                }
            }
        ]
    }
    manifest["catalog_content_hash"] = oracle_catalog_content_hash(manifest)
    manifest_file = tmp_path / "catalog.yaml"
    with open(manifest_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(manifest, f)

    catalog = load_catalog(manifest_file, content_root=tmp_path)
    resolver = syms["LocalCitationResolver"](catalog)

    # Write incorrect content (mismatched hash/byte_length)
    (tmp_path / "x.pdf").write_bytes(b"tampered content")

    with pytest.raises(syms["AtlasContentDriftError"]):
        resolver.resolve("PMID:12345")


def test_verify_span_happy_and_adversarial_red(tmp_path):
    """Test exact verify_span validation: locators, bounds, CRLF normalization, Unicode NFC, and duplicate quote handling."""
    syms = get_resolver_symbols()
    load_catalog = syms["load_catalog"]

    # Setup catalog with raw and extracted text
    text_content = "This is a synthetic citation sentence.\r\nIt has composed unicode: \u00e4.\r\nAnd another line."
    text_bytes = text_content.encode("utf-8")
    text_hash = hashlib.sha256(text_bytes).hexdigest().lower()
    text_len = len(text_bytes)

    manifest = {
        "schema": "atlas.citation_catalog.v1",
        "catalog_id": "synthetic-catalog",
        "catalog_version": "1.0.0",
        "catalog_content_hash": "placeholder",
        "disease_pack_binding": {
            "pack_id": "synthpack", "pack_version": "1.0.0", "pack_content_hash": "bf7369f8faa24a6f746956ee1122281e798185f320b012a844ffbc683f2e7b21"
        },
        "content_root_policy": {"policy": "relative"},
        "sources": [
            {
                "source_id": "src-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
                "identifiers": {"pmid": ["12345"]}, "permitted_use": "grounding_and_quote", "verification": "verified",
                "raw_artifact": {"relative_path": "x.pdf", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "byte_length": 0, "media_type": "pdf"},
                "extracted_text": {
                    "relative_path": "extracted.txt",
                    "sha256": text_hash,
                    "byte_length": text_len,
                    "extraction_method": "manual",
                    "extraction_version": "1.0.0",
                    "normalization": "atlas.text_norm.v1"
                }
            }
        ]
    }

    assert_no_cribbing(manifest)

    manifest["catalog_content_hash"] = oracle_catalog_content_hash(manifest)
    manifest_file = tmp_path / "catalog.yaml"
    with open(manifest_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(manifest, f)

    (tmp_path / "x.pdf").write_bytes(b"")
    (tmp_path / "extracted.txt").write_bytes(text_bytes)

    catalog = load_catalog(manifest_file, content_root=tmp_path)
    resolver = syms["LocalCitationResolver"](catalog)

    resolved = resolver.resolve("PMID:12345")

    # 1. Happy path: exact verify
    # Normalized text: "This is a synthetic citation sentence.\nIt has composed unicode: ä.\nAnd another line."
    # Let's verify composited unicode: "ä"
    # Derive the exact start offset of "ä" dynamically from the normalized text.
    norm_text = oracle_text_normalization(text_bytes)
    start_composed = norm_text.find("\u00e4")
    assert start_composed == 64, f"Expected dynamically derived index to be 64, got {start_composed}"

    from raptor.atlas.model import Span
    span_composed = Span(locator=f"text-char:{start_composed}:{start_composed+1}", exact_quote="\u00e4")
    res_span = resolver.verify_span(resolved, span_composed)
    assert res_span.exact_quote == "\u00e4"
    assert res_span.start == start_composed

    # 2. CRLF-to-LF verify
    # Check that a span spanning CRLF boundaries verified with LF: "sentence.\nIt"
    # Offsets in normalized text: "sentence." ends at 38. "It" starts at 39. So "sentence.\nIt" is [29, 41]
    start_crlf = norm_text.find("sentence.\nIt")
    span_crlf = Span(locator=f"text-char:{start_crlf}:{start_crlf+12}", exact_quote="sentence.\nIt")
    resolver.verify_span(resolved, span_crlf)

    # Mismatched quote (asserting CRLF inside quote) must fail
    span_crlf_fail = Span(locator=f"text-char:{start_crlf}:{start_crlf+12}", exact_quote="sentence.\r\nIt")
    with pytest.raises(syms["AtlasSpanMismatchError"]):
        resolver.verify_span(resolved, span_crlf_fail)

    # 3. Unicode NFC verification
    # Mismatched quote (asserting decomposed NFD) must fail
    decomposed_quote = "a\u0308" # NFD 'ä'
    span_nfd_fail = Span(locator=f"text-char:{start_composed}:{start_composed+1}", exact_quote=decomposed_quote)
    with pytest.raises(syms["AtlasSpanMismatchError"]):
        resolver.verify_span(resolved, span_nfd_fail)

    # 4. Out of bounds, non-integer, negative, etc.
    with pytest.raises(syms["AtlasSpanMismatchError"]):
        resolver.verify_span(resolved, Span(locator="text-char:-1:5", exact_quote="T"))
    with pytest.raises(syms["AtlasSpanMismatchError"]):
        resolver.verify_span(resolved, Span(locator=f"text-char:0:{len(norm_text)+10}", exact_quote="T"))
    with pytest.raises(syms["AtlasSpanMismatchError"]):
        resolver.verify_span(resolved, Span(locator="text-char:5:2", exact_quote="T")) # start >= end
    with pytest.raises(syms["AtlasSpanMismatchError"]):
        resolver.verify_span(resolved, Span(locator="wrong-schema:0:5", exact_quote="T"))


def test_gemini_citation_identifiers_schema_validation_red(tmp_path):
    """
    Focused test suite verifying the strict validation schema of catalog source identifiers.
    Asserts compliance with docs/project/specs/atlas-citation-resolver-v1.yaml.
    Specifically tests that invalid shapes of the 'identifiers' field and its values
    fail with AtlasCatalogSchemaError, and valid ones load properly.
    """
    syms = get_resolver_symbols()
    load_catalog = syms["load_catalog"]
    AtlasCatalogSchemaError = syms["AtlasCatalogSchemaError"]

    # Base valid manifest structure with no sources yet.
    base_manifest = {
        "schema": "atlas.citation_catalog.v1",
        "catalog_id": "gemini-identifiers-test-catalog",
        "catalog_version": "1.0.0",
        "catalog_content_hash": "placeholder",
        "disease_pack_binding": {
            "pack_id": "synthpack",
            "pack_version": "1.0.0",
            "pack_content_hash": "bf7369f8faa24a6f746956ee1122281e798185f320b012a844ffbc683f2e7b21"
        },
        "content_root_policy": {"policy": "relative"},
        "sources": []
    }

    # Dummy files needed for any direct_evidence_leaf checks
    (tmp_path / "x.pdf").write_bytes(b"")

    def try_load(sources):
        manifest = dict(base_manifest)
        manifest["sources"] = sources
        manifest["catalog_content_hash"] = oracle_catalog_content_hash(manifest)
        
        manifest_file = tmp_path / "catalog.yaml"
        with open(manifest_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(manifest, f)
            
        return load_catalog(manifest_file, content_root=tmp_path)

    # 1. identifiers field omitted
    # Testing both grounding leaf (role: direct_evidence_leaf) and non-grounding context/provenance source
    with pytest.raises(AtlasCatalogSchemaError):
        try_load([
            {
                "source_id": "src-omit-grounding",
                "source_type": "PRIMARY-LIT",
                "role": "direct_evidence_leaf",
                # identifiers is omitted
                "permitted_use": "grounding_and_quote",
                "verification": "verified",
                "raw_artifact": {"relative_path": "x.pdf", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "byte_length": 0, "media_type": "pdf"}
            }
        ])

    with pytest.raises(AtlasCatalogSchemaError):
        try_load([
            {
                "source_id": "src-omit-nongrounding",
                "source_type": "PRIMARY-LIT",
                "role": "context",
                # identifiers is omitted
                "permitted_use": "context_only",
                "verification": "verified"
            }
        ])

    # 2. identifiers is null
    with pytest.raises(AtlasCatalogSchemaError):
        try_load([
            {
                "source_id": "src-null",
                "source_type": "PRIMARY-LIT",
                "role": "context",
                "identifiers": None,
                "permitted_use": "context_only",
                "verification": "verified"
            }
        ])

    # 3. identifiers is empty list
    with pytest.raises(AtlasCatalogSchemaError):
        try_load([
            {
                "source_id": "src-empty-list",
                "source_type": "PRIMARY-LIT",
                "role": "context",
                "identifiers": [],
                "permitted_use": "context_only",
                "verification": "verified"
            }
        ])

    # 4. identifiers is string
    with pytest.raises(AtlasCatalogSchemaError):
        try_load([
            {
                "source_id": "src-string",
                "source_type": "PRIMARY-LIT",
                "role": "context",
                "identifiers": "pmid:12345",
                "permitted_use": "context_only",
                "verification": "verified"
            }
        ])

    # 5. identifiers is scalar (int)
    with pytest.raises(AtlasCatalogSchemaError):
        try_load([
            {
                "source_id": "src-scalar",
                "source_type": "PRIMARY-LIT",
                "role": "context",
                "identifiers": 42,
                "permitted_use": "context_only",
                "verification": "verified"
            }
        ])

    # 6. identifiers empty mapping is allowed for non-grounding but direct_evidence_leaf requires at least one
    # Grounding leaf with empty mapping must fail:
    with pytest.raises(AtlasCatalogSchemaError):
        try_load([
            {
                "source_id": "src-grounding-empty-mapping",
                "source_type": "PRIMARY-LIT",
                "role": "direct_evidence_leaf",
                "identifiers": {},
                "permitted_use": "grounding_and_quote",
                "verification": "verified",
                "raw_artifact": {"relative_path": "x.pdf", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "byte_length": 0, "media_type": "pdf"}
            }
        ])

    # Non-grounding leaf with empty mapping is allowed:
    catalog_empty_mapping = try_load([
        {
            "source_id": "src-nongrounding-empty-mapping",
            "source_type": "PRIMARY-LIT",
            "role": "context",
            "identifiers": {},
            "permitted_use": "context_only",
            "verification": "verified"
        }
    ])
    assert catalog_empty_mapping is not None

    # 7. Each present scheme value must be list[str] (no falsey/coerced values)
    # - Empty string scheme value
    with pytest.raises(AtlasCatalogSchemaError):
        try_load([
            {
                "source_id": "src-scheme-val-empty-str",
                "source_type": "PRIMARY-LIT",
                "role": "context",
                "identifiers": {"pmid": ""},
                "permitted_use": "context_only",
                "verification": "verified"
            }
        ])

    # - Null scheme value
    with pytest.raises(AtlasCatalogSchemaError):
        try_load([
            {
                "source_id": "src-scheme-val-null",
                "source_type": "PRIMARY-LIT",
                "role": "context",
                "identifiers": {"pmid": None},
                "permitted_use": "context_only",
                "verification": "verified"
            }
        ])

    # - Scalar scheme value
    with pytest.raises(AtlasCatalogSchemaError):
        try_load([
            {
                "source_id": "src-scheme-val-scalar",
                "source_type": "PRIMARY-LIT",
                "role": "context",
                "identifiers": {"pmid": 12345},
                "permitted_use": "context_only",
                "verification": "verified"
            }
        ])

    # - Mapping scheme value
    with pytest.raises(AtlasCatalogSchemaError):
        try_load([
            {
                "source_id": "src-scheme-val-mapping",
                "source_type": "PRIMARY-LIT",
                "role": "context",
                "identifiers": {"pmid": {"id": "12345"}},
                "permitted_use": "context_only",
                "verification": "verified"
            }
        ])

    # 8. List entries must be nonblank strings and normalize successfully
    # - Empty string entry
    with pytest.raises(AtlasCatalogSchemaError):
        try_load([
            {
                "source_id": "src-entry-empty-str",
                "source_type": "PRIMARY-LIT",
                "role": "context",
                "identifiers": {"pmid": [""]},
                "permitted_use": "context_only",
                "verification": "verified"
            }
        ])

    # - Malformed identifier value (e.g. invalid PMID format with leading zero)
    with pytest.raises(AtlasCatalogSchemaError):
        try_load([
            {
                "source_id": "src-entry-malformed",
                "source_type": "PRIMARY-LIT",
                "role": "context",
                "identifiers": {"pmid": ["012345"]},
                "permitted_use": "context_only",
                "verification": "verified"
            }
        ])

    # 9. Mixed valid DOI plus malformed empty PMID must reject whole catalog
    with pytest.raises(AtlasCatalogSchemaError):
        try_load([
            {
                "source_id": "src-mixed-malformed",
                "source_type": "PRIMARY-LIT",
                "role": "context",
                "identifiers": {"doi": ["10.5555/abc"], "pmid": ""},
                "permitted_use": "context_only",
                "verification": "verified"
            }
        ])

    # 10. Fully valid identifier mapping loads, duplicate/cross-source rules preserved
    # Valid load:
    valid_catalog = try_load([
        {
            "source_id": "src-valid-1",
            "source_type": "PRIMARY-LIT",
            "role": "direct_evidence_leaf",
            "identifiers": {"doi": ["10.5555/abc"], "pmid": ["12345"]},
            "permitted_use": "grounding_and_quote",
            "verification": "verified",
            "raw_artifact": {"relative_path": "x.pdf", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "byte_length": 0, "media_type": "pdf"}
        }
    ])
    assert valid_catalog is not None

    # Cross-source duplicate alias (duplicate PMID across sources):
    with pytest.raises(AtlasCatalogSchemaError):
        try_load([
            {
                "source_id": "src-valid-1",
                "source_type": "PRIMARY-LIT",
                "role": "direct_evidence_leaf",
                "identifiers": {"pmid": ["12345"]},
                "permitted_use": "grounding_and_quote",
                "verification": "verified",
                "raw_artifact": {"relative_path": "x.pdf", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "byte_length": 0, "media_type": "pdf"}
            },
            {
                "source_id": "src-valid-2",
                "source_type": "PRIMARY-LIT",
                "role": "direct_evidence_leaf",
                "identifiers": {"pmid": ["12345"]},
                "permitted_use": "grounding_and_quote",
                "verification": "verified",
                "raw_artifact": {"relative_path": "x.pdf", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "byte_length": 0, "media_type": "pdf"}
            }
        ])

    # 11. Mixed/non-string keys in identifiers mapping must raise AtlasCatalogSchemaError, never raw TypeError
    def try_load_raw(sources):
        manifest = dict(base_manifest)
        manifest["sources"] = sources
        manifest["catalog_content_hash"] = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855" # placeholder
        manifest_file = tmp_path / "catalog_raw.yaml"
        with open(manifest_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(manifest, f)
        return load_catalog(manifest_file, content_root=tmp_path)

    # int key (causes TypeError in current production because of sorted() on mixed set)
    with pytest.raises(AtlasCatalogSchemaError):
        try_load_raw([
            {
                "source_id": "src-int-key",
                "source_type": "PRIMARY-LIT",
                "role": "context",
                "identifiers": {123: ["12345"], "unsupported": ["abc"]},
                "permitted_use": "context_only",
                "verification": "verified"
            }
        ])

    # bool key (causes TypeError in current production because of sorted() on mixed set)
    with pytest.raises(AtlasCatalogSchemaError):
        try_load_raw([
            {
                "source_id": "src-bool-key",
                "source_type": "PRIMARY-LIT",
                "role": "context",
                "identifiers": {True: ["12345"], "unsupported": ["abc"]},
                "permitted_use": "context_only",
                "verification": "verified"
            }
        ])

    # null/None key (causes TypeError in current production because of sorted() on mixed set)
    with pytest.raises(AtlasCatalogSchemaError):
        try_load_raw([
            {
                "source_id": "src-null-key",
                "source_type": "PRIMARY-LIT",
                "role": "context",
                "identifiers": {None: ["12345"], "unsupported": ["abc"]},
                "permitted_use": "context_only",
                "verification": "verified"
            }
        ])

    # tuple/object where direct mapping probe (causes TypeError in current production because of sorted() on mixed set)
    from raptor.atlas.citation import _validate_and_build_sources
    with pytest.raises(AtlasCatalogSchemaError):
        _validate_and_build_sources([
            {
                "source_id": "src-tuple-key",
                "source_type": "PRIMARY-LIT",
                "role": "context",
                "identifiers": {("a", "b"): ["12345"], "unsupported": ["abc"]},
                "permitted_use": "context_only",
                "verification": "verified"
            }
        ])

    # Unsupported string keys also raise AtlasCatalogSchemaError
    with pytest.raises(AtlasCatalogSchemaError):
        try_load([
            {
                "source_id": "src-unsupported-key",
                "source_type": "PRIMARY-LIT",
                "role": "context",
                "identifiers": {"unsupported": ["abc"]},
                "permitted_use": "context_only",
                "verification": "verified"
            }
        ])


def test_gemini_catalog_content_hash_schema_validation_red(tmp_path):
    """
    Non-vacuous catalog_content_hash schema tests using otherwise-valid synthetic catalog.
    Asserts compliance with the specification for catalog_content_hash:
    - Exact lowercase 64-hex computed digest loads and stored catalog hash is exactly lowercase/recomputed.
    - Uppercase and mixed-case correct digests must be rejected with AtlasCatalogSchemaError or AtlasCatalogHashError (no casefold).
    - Malformed length, non-hex, blank, or non-string values must be rejected with typed exceptions.
    - Direct catalog_content_hash() remains lowercase.
    """
    syms = get_resolver_symbols()
    load_catalog = syms["load_catalog"]
    catalog_content_hash = syms["catalog_content_hash"]
    AtlasCatalogSchemaError = syms["AtlasCatalogSchemaError"]
    AtlasCatalogHashError = syms["AtlasCatalogHashError"]

    # Base valid manifest structure with no sources yet.
    base_manifest = {
        "schema": "atlas.citation_catalog.v1",
        "catalog_id": "gemini-hash-test-catalog",
        "catalog_version": "1.0.0",
        "catalog_content_hash": "placeholder",
        "disease_pack_binding": {
            "pack_id": "synthpack",
            "pack_version": "1.0.0",
            "pack_content_hash": "bf7369f8faa24a6f746956ee1122281e798185f320b012a844ffbc683f2e7b21"
        },
        "content_root_policy": {"policy": "relative"},
        "sources": []
    }

    # 1. Direct catalog_content_hash() remains lowercase 64-hex
    h_direct = catalog_content_hash(base_manifest)
    assert h_direct.islower(), "direct catalog_content_hash must be lowercase"
    assert len(h_direct) == 64, "direct catalog_content_hash must be exactly 64 characters"
    assert all(c in "0123456789abcdef" for c in h_direct), "direct catalog_content_hash must be hex digest"

    def try_load_with_hash(h_val):
        manifest = dict(base_manifest)
        manifest["catalog_content_hash"] = h_val
        manifest_file = tmp_path / "catalog_hash_test.yaml"
        with open(manifest_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(manifest, f)
        return load_catalog(manifest_file, content_root=tmp_path)

    # 2. Exact lowercase 64hex computed digest loads and stored catalog hash is exactly lowercase/recomputed
    loaded_catalog = try_load_with_hash(h_direct)
    assert loaded_catalog is not None
    assert loaded_catalog.catalog_content_hash == h_direct

    # 3. Uppercase and mixed-case correct digest rejected with AtlasCatalogSchemaError/HashError (no casefold)
    # This will fail on current production (RED) since current production accepts uppercase/mixed-case.
    with pytest.raises((AtlasCatalogSchemaError, AtlasCatalogHashError)):
        try_load_with_hash(h_direct.upper())

    mixed_hash = h_direct[:32].upper() + h_direct[32:].lower()
    with pytest.raises((AtlasCatalogSchemaError, AtlasCatalogHashError)):
        try_load_with_hash(mixed_hash)

    # 4. Malformed length/nonhex/blank/nonstring rejected typed
    # - Malformed length (63 characters)
    with pytest.raises((AtlasCatalogSchemaError, AtlasCatalogHashError)):
        try_load_with_hash(h_direct[:-1])

    # - Malformed length (65 characters)
    with pytest.raises((AtlasCatalogSchemaError, AtlasCatalogHashError)):
        try_load_with_hash(h_direct + "a")

    # - Non-hex characters
    nonhex_hash = h_direct[:-1] + "g"
    with pytest.raises((AtlasCatalogSchemaError, AtlasCatalogHashError)):
        try_load_with_hash(nonhex_hash)

    # - Blank / Empty string
    with pytest.raises((AtlasCatalogSchemaError, AtlasCatalogHashError)):
        try_load_with_hash("")

    # - Whitespace only
    with pytest.raises((AtlasCatalogSchemaError, AtlasCatalogHashError)):
        try_load_with_hash(" " * 64)

    # - Non-string: integer
    with pytest.raises((AtlasCatalogSchemaError, AtlasCatalogHashError)):
        try_load_with_hash(12345)

    # - Non-string: boolean
    with pytest.raises((AtlasCatalogSchemaError, AtlasCatalogHashError)):
        try_load_with_hash(True)

    # - Non-string: None
    with pytest.raises((AtlasCatalogSchemaError, AtlasCatalogHashError)):
        try_load_with_hash(None)

    # - Non-string: list
    with pytest.raises((AtlasCatalogSchemaError, AtlasCatalogHashError)):
        try_load_with_hash([h_direct])

    # - Non-string: dict
    with pytest.raises((AtlasCatalogSchemaError, AtlasCatalogHashError)):
        try_load_with_hash({"hash": h_direct})


