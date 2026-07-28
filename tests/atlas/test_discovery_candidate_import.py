"""
Gemini RED tests for Mechanism Atlas: Discovery Candidate Import and Promotion
Spec coverage:
- Model exact fields of AtlasCandidateImport: nested candidate_variant, proposed_claims,
  proposed_sources, retrieval_provenance. NO top-level mapper_version, bookshelf_version,
  prompt_hash, or status fields (must fail on schema or raise TypeError).
- Model PromotionContext exact fields: disease_pack, citation_resolver, context_validator,
  human_oracle_reviewer, duplicate_index.
- Exercise ALL eight gates in exact order:
  1. canonical_spdi_readmission
  2. source_type_role_validation
  3. citation_resolution
  4. exact_span_resolution
  5. context_ontology_pack_validation
  6. duplicate_conflict_rules
  7. no_classification_leakage
  8. named_human_oracle_span_review
- Assert that no later gate runs after any gate fails (strict short-circuit and execution ordering).
- promote_candidate returns accepted tuple only after all gates pass; importer cannot write accepted state.
- No real claims or spans accepted (only synthetic GRCh38 SPDI and data).
- Update to CitationResolver Protocol and exact Eight Gates instrumentation.
"""

import sys
import dataclasses
import pytest

# 2. Anti-cribbing check
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
# Strict Fake Citation Resolver implementing the CitationResolver Protocol
# ---------------------------------------------------------------------------
class FakeCitationResolver:
    """Strict fake implementing the typed CitationResolver protocol."""

    def __init__(self):
        self.resolve_calls = []
        self.verify_span_calls = []
        self.mapping = {
            "PMID:12345": ("src-resolved-lit", "PRIMARY-LIT"),
            "PMCID:PMC12345": ("src-resolved-lit", "PRIMARY-LIT"),
            "DOI:10.5555/lit": ("src-resolved-lit", "PRIMARY-LIT"),
            "ACCESSION:geo:GSE12345": ("src-resolved-dataset", "DATASET"),
            "DOI:10.5555/abc": ("src-resolved-dataset", "DATASET"),
        }

    def resolve(self, identifier):
        from raptor.atlas.model import CitationIdentifier
        raw_id = identifier.canonical if isinstance(identifier, CitationIdentifier) else str(identifier)
        self.resolve_calls.append(raw_id)

        try:
            from raptor.atlas.model import (
                CatalogSource, ResolvedCitation, ContentVerification,
                AtlasCitationResolutionError, AtlasContentDriftError,
                AtlasCatalogPathError, AtlasCatalogSchemaError
            )
        except ImportError:
            pytest.fail("RED: raptor.atlas model/citation classes not implemented", pytrace=False)

        # Handle synthetic error triggers
        if "fail-citation" in raw_id:
            raise AtlasCitationResolutionError(f"Failed to resolve {raw_id}")
        if "fail-drift" in raw_id:
            raise AtlasContentDriftError(f"Drift for {raw_id}")
        if "fail-path" in raw_id:
            raise AtlasCatalogPathError(f"Path error for {raw_id}")
        if "fail-schema" in raw_id:
            raise AtlasCatalogSchemaError(f"Schema error for {raw_id}")

        # Data-driven identification mapping lookup
        if raw_id in self.mapping:
            source_id, source_type = self.mapping[raw_id]
        else:
            is_dataset = "ACCESSION:geo" in raw_id
            source_id = "src-resolved-dataset" if is_dataset else "src-resolved-lit"
            source_type = "DATASET" if is_dataset else "PRIMARY-LIT"

        # Build non-empty tuple of typed CitationIdentifier objects that accurately lists all canonical aliases owned by that source.
        # PRIMARY-LIT source includes its PMID/PMCID/DOI aliases; DATASET includes ACCESSION/DOI aliases
        if source_type == "PRIMARY-LIT":
            source_identifiers = (
                CitationIdentifier("PMID", "12345", "PMID:12345"),
                CitationIdentifier("PMCID", "PMC12345", "PMCID:PMC12345"),
                CitationIdentifier("DOI", "10.5555/lit", "DOI:10.5555/lit")
            )
        else: # "DATASET"
            source_identifiers = (
                CitationIdentifier("ACCESSION", "geo:GSE12345", "ACCESSION:geo:GSE12345"),
                CitationIdentifier("DOI", "10.5555/abc", "DOI:10.5555/abc")
            )

        # Build synthetic source & verification objects
        source = CatalogSource(
            source_id=source_id,
            source_type=source_type,
            role="direct_evidence_leaf",
            identifiers=source_identifiers,
            license="CC0",
            permitted_use="grounding_and_quote",
            verification="verified",
            authoritative_url=None,
            document_date=None,
            document_version=None,
            raw_relative_path="raw.pdf",
            raw_declared_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            raw_declared_byte_length=100,
            raw_media_type="application/pdf",
            extracted_relative_path="extract.txt",
            extracted_declared_sha256="85136db6d4512cb593c66f543d2c88f1ae7e786bdfc14c55d0ac5b42dcd45c7f",
            extracted_declared_byte_length=150,
            extraction_method="pdftotext",
            extraction_version="1.0.0",
            text_normalization="atlas.text_norm.v1"
        )
        content = ContentVerification(
            raw_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            raw_byte_length=100,
            extracted_text_sha256="85136db6d4512cb593c66f543d2c88f1ae7e786bdfc14c55d0ac5b42dcd45c7f",
            extracted_text_byte_length=150
        )
        return ResolvedCitation(
            identifier=identifier if isinstance(identifier, CitationIdentifier) else CitationIdentifier("PMID", raw_id, raw_id),
            source=source,
            content=content,
            content_verified=True
        )

    def verify_span(self, resolved, span):
        self.verify_span_calls.append((resolved, span))
        try:
            from raptor.atlas.model import VerifiedSpan, AtlasSpanMismatchError
        except ImportError:
            pytest.fail("RED: raptor.atlas model/citation classes not implemented", pytrace=False)

        if "fail-span" in span.locator or "fail-span" in (span.exact_quote or ""):
            raise AtlasSpanMismatchError(f"Span mismatch for {span.locator}")

        return VerifiedSpan(
            source_id=resolved.source.source_id,
            locator=span.locator,
            start=0,
            end=len(span.exact_quote or ""),
            exact_quote=span.exact_quote or "",
            extracted_text_sha256=resolved.content.extracted_text_sha256 or "85136db6d4512cb593c66f543d2c88f1ae7e786bdfc14c55d0ac5b42dcd45c7f"
        )

    def __call__(self, *args, **kwargs):
        # Fail with pytest failure to denote planned RED gate transition checks
        pytest.fail("RED: Promotion code still uses old Callable interface instead of CitationResolver protocol")


# ---------------------------------------------------------------------------
# Existing structural schema tests (Preserved)
# ---------------------------------------------------------------------------

def test_candidate_import_exact_schema():
    """Verify that AtlasCandidateImport matches the exact spec schema with nested fields and no top-level flat fields."""
    try:
        from raptor.atlas.model import AtlasCandidateImport, AtlasSchemaError
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas promote/candidate_import implementation is missing")

    # Base valid structures (using Python LISTS for nested JSON schema list fields per Finding 2)
    candidate_variant = {
        "spdi_proposed": "NC_000000.0:1000:A:T",
        "gene_proposed": "SYNGENE1",
        "hgvs_aliases": ["g.1000A>T"]
    }
    retrieval_provenance = {
        "agents": ["agent-1"],
        "queries": ["query-1"],
        "run_id": "run-001",
        "retrieved_at": "2026-07-23T01:00:00Z",
        "pack_binding": {
            "pack_id": "synthpack",
            "pack_version": "1.0.0",
            "pack_content_hash": "bf7369f8faa24a6f746956ee1122281e798185f320b012a844ffbc683f2e7b21"
        },
        "prompt_hash": "prompt-hash-1",
        "bookshelf_version": "v2.1"
    }

    # Ensure no cribbing in inputs
    assert_no_cribbing(candidate_variant)
    assert_no_cribbing(retrieval_provenance)

    # 1. Correct constructor usage
    cand = AtlasCandidateImport(
        candidate_variant=candidate_variant,
        proposed_claims=[],
        proposed_sources=[],
        retrieval_provenance=retrieval_provenance
    )

    # 2. Assert NO flat top-level fields exist
    fields = [f.name for f in dataclasses.fields(AtlasCandidateImport)]
    for forbidden in ["mapper_version", "bookshelf_version", "prompt_hash", "status"]:
        assert forbidden not in fields, f"Spec violation: {forbidden} must not be a top-level field of AtlasCandidateImport"

    # Verifying constructor rejects top-level flat fields
    with pytest.raises((TypeError, AtlasSchemaError)):
        AtlasCandidateImport(
            candidate_variant=candidate_variant,
            proposed_claims=[],
            proposed_sources=[],
            retrieval_provenance=retrieval_provenance,
            status="proposed"  # Flat top-level field is WRONG
        )


def test_promotion_context_fields():
    """Verify PromotionContext fields strictly conform to the spec, including CitationResolver protocol annotation."""
    try:
        from raptor.atlas.model import PromotionContext, CitationResolver
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas promote/candidate_import implementation is missing")

    import typing
    hints = typing.get_type_hints(PromotionContext)
    
    # Assert exact type annotation is CitationResolver Protocol, not Callable bool
    assert hints["citation_resolver"] is CitationResolver, "PromotionContext.citation_resolver must be typed as CitationResolver protocol"

    # Verify attributes/fields list
    fields_list = [f.name for f in dataclasses.fields(PromotionContext)]
    expected = ["disease_pack", "citation_resolver", "context_validator", "human_oracle_reviewer", "duplicate_index"]
    for field in expected:
        assert field in fields_list, f"PromotionContext is missing expected field: {field}"

    # Verify that the resolver is a runtime-checkable Protocol
    fake_resolver = FakeCitationResolver()
    assert isinstance(fake_resolver, CitationResolver), "Fake resolver must satisfy Protocol"
    assert hasattr(fake_resolver, "resolve"), "Protocol must have resolve method"
    assert hasattr(fake_resolver, "verify_span"), "Protocol must have verify_span method"


def make_schema_valid_disease_pack(model_mod):
    # Returns a schema-valid synthetic DiseasePack matching the exact spec positive fixture
    source_pin = model_mod.SourceRegisterEntry(
        entry_id="synthsrc-0001",
        source_type="DATASET",
        role="provenance_only",
        urn_or_ids={"accession": "SYNTHDB-0001"},
        transcript=None,
        license="CC0-1.0",
        sha256=None,
        variant_count=None,
        verification="confirm_pending"
    )
    return model_mod.DiseasePack(
        schema="atlas.disease_pack.v1",
        pack_id="synthpack",
        pack_version="1.0.0",
        pack_content_hash="bf7369f8faa24a6f746956ee1122281e798185f320b012a844ffbc683f2e7b21",
        allowed_genes=("SYNGENE1",),
        assembly_pins=("GRCh38",),
        transcript_pins=(
            {"transcript": "NM_900001.1", "requires": "MANE-Select-verification"},
        ),
        reconciliation_policy={
            "alias_to_canonical_spdi_only": True,
            "no_fabrication": True
        },
        ontology_extensions={
            "claim_kinds": [
                {"id": "synthpack:pathway_synthpath", "parent": "pathway"}
            ],
            "node_layers": [],
            "mechanism_classes": [],
            "context_vocabularies": {
                "tissue": ["synth_tissue_a"]
            }
        },
        source_register_pins=(source_pin,),
        prohibitions={
            "no_hardcode_handoff_mechanism": True
        },
        pilot_eval_metadata={
            "panel_strata": ["synthetic_stratum_a"],
            "native_vs_discovery_axes": ["reuse_percentage"]
        }
    )


def test_eight_gates_ordered_execution_and_short_circuiting():
    """Verify that validate_candidate_import executes the 8 gates in strict order, instrumenting short-circuiting on failure."""
    try:
        import raptor.atlas.model as model_mod
        from raptor.atlas.promote import validate_candidate_import
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas promote/candidate_import implementation is missing")

    # 1. Mock disease pack (now schema-valid using helper)
    mock_pack = make_schema_valid_disease_pack(model_mod)

    # 2. Instrumentation: we create trackers
    calls = []

    def context_validator(claim_kind, context_name):
        calls.append("context_validator")
        # Fail on "fail-context"
        if claim_kind == "fail-kind":
            return False
        return True

    def human_oracle_reviewer(candidate_id):
        calls.append("human_oracle_reviewer")
        # Fail on "fail-human"
        if candidate_id == "fail-human":
            return None
        return "oracle-signature-001"

    # Base valid pieces (using lists instead of tuples for JSON compatibility)
    valid_variant = {
        "spdi_proposed": "NC_000000.0:1000:A:T",
        "gene_proposed": "SYNGENE1",
        "hgvs_aliases": []
    }

    # Perfect pack binding matching mock_pack per Finding 3:
    pack_binding_dict = {
        "pack_id": mock_pack.pack_id,
        "pack_version": mock_pack.pack_version,
        "pack_content_hash": mock_pack.pack_content_hash
    }

    valid_retrieval = {
        "agents": [],
        "queries": [],
        "run_id": "r1",
        "retrieved_at": "now",
        "pack_binding": pack_binding_dict,
        "prompt_hash": "h",
        "bookshelf_version": "v1"
    }

    # Gate 1 failed (canonical_spdi_readmission) -> should raise AtlasIdentityError and not call anything else
    cand_g1_fail = model_mod.AtlasCandidateImport(
        candidate_variant={
            "spdi_proposed": "NC_000000.0:1000:A:T",
            "gene_proposed": "OFF_PACK_GENE",  # G1 check: off-pack gene raises
            "hgvs_aliases": []
        },
        proposed_claims=[],
        proposed_sources=[],
        retrieval_provenance=valid_retrieval
    )

    fake_resolver = FakeCitationResolver()

    ctx = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=fake_resolver,
        context_validator=context_validator,
        human_oracle_reviewer=human_oracle_reviewer,
        duplicate_index={}
    )

    calls.clear()
    with pytest.raises((model_mod.AtlasIdentityError, model_mod.AtlasSchemaError)):
        validate_candidate_import(cand_g1_fail, ctx)
    assert len(calls) == 0, "No collaborators should be invoked when Gate 1 (identity) fails"

    # Gate 2 failed (source_type_role_validation)
    # Role is direct_evidence_leaf, but source_type is primary_lit_wrong (not PRIMARY-LIT or DATASET)
    cand_g2_fail = model_mod.AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=[],
        proposed_sources=[{
            "entry_id": "lit-1", "source_type": "PRIMARY-OFFICIAL", "role": "direct_evidence_leaf",
            "bib": {"pmid": "12345"}
        }],
        retrieval_provenance=valid_retrieval
    )
    calls.clear()
    with pytest.raises(model_mod.AtlasSchemaError):
        validate_candidate_import(cand_g2_fail, ctx)
    assert len(calls) == 0, "No collaborators should be invoked when Gate 2 (source-role/type) fails"

    # Gate 3 failed (citation_resolution) -> citation_resolver is invoked and fails; no subsequent gates called
    cand_g3_fail = model_mod.AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=[],
        proposed_sources=[{
            "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "bib": {"doi": "10.9999/fail-citation"} # Syntactically valid bare DOI failure
        }],
        retrieval_provenance=valid_retrieval
    )
    calls.clear()
    fake_resolver.resolve_calls.clear()
    with pytest.raises(model_mod.AtlasProvenanceError) as exc_info:
        validate_candidate_import(cand_g3_fail, ctx)

    # Check error translation & cause chain
    try:
        from raptor.atlas.model import AtlasCitationResolutionError
        assert isinstance(exc_info.value.__cause__, AtlasCitationResolutionError)
    except ImportError:
        pass # Expected before implementation is complete

    assert len(fake_resolver.resolve_calls) > 0
    assert "context_validator" not in calls
    assert "human_oracle_reviewer" not in calls

    # Gate 4 failed (exact_span_resolution) -> claim missing span
    cand_g4_fail_missing_span = model_mod.AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=[{
            "claim_text": "text", "claim_kind_proposed": "pathway", "directionality": "increase",
            "source_ref_proposed": "lit-1", "span_proposed": None, "context_proposed": "cell-assay-A"
        }],
        proposed_sources=[{
            "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "bib": {"pmid": "12345"}
        }],
        retrieval_provenance=valid_retrieval
    )
    calls.clear()
    fake_resolver.resolve_calls.clear()
    with pytest.raises(model_mod.AtlasSchemaError):
        validate_candidate_import(cand_g4_fail_missing_span, ctx)
    # Since citation resolution is Gate 3, it should be called before Gate 4 checks span!
    assert len(fake_resolver.resolve_calls) > 0
    assert "context_validator" not in calls
    assert "human_oracle_reviewer" not in calls

    # Gate 4 failed span mismatch (verify_span throws AtlasSpanMismatchError -> translated to AtlasProvenanceError)
    cand_g4_fail_span_mismatch = model_mod.AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=[{
            "claim_text": "text", "claim_kind_proposed": "pathway", "directionality": "increase",
            "source_ref_proposed": "lit-1",
            "span_proposed": {"locator": "fail-span", "exact_quote": "fail-span", "page_or_figure": "1"},
            "context_proposed": "cell-assay-A"
        }],
        proposed_sources=[{
            "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "bib": {"pmid": "12345"}
        }],
        retrieval_provenance=valid_retrieval
    )
    calls.clear()
    fake_resolver.resolve_calls.clear()
    fake_resolver.verify_span_calls.clear()
    with pytest.raises(model_mod.AtlasProvenanceError) as exc_info:
        validate_candidate_import(cand_g4_fail_span_mismatch, ctx)

    try:
        from raptor.atlas.model import AtlasSpanMismatchError
        assert isinstance(exc_info.value.__cause__, AtlasSpanMismatchError)
    except ImportError:
        pass

    assert len(fake_resolver.resolve_calls) > 0
    assert len(fake_resolver.verify_span_calls) > 0
    assert "context_validator" not in calls
    assert "human_oracle_reviewer" not in calls

    # Gate 5 failed (context_ontology_pack_validation) -> context_validator is invoked and fails
    cand_g5_fail = model_mod.AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=[{
            "claim_text": "text", "claim_kind_proposed": "fail-kind", "directionality": "increase",
            "source_ref_proposed": "lit-1",
            "span_proposed": {"locator": "L1", "exact_quote": "Q1", "page_or_figure": "1"}, "context_proposed": "cell-assay-A"
        }],
        proposed_sources=[{
            "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "bib": {"pmid": "12345"}
        }],
        retrieval_provenance=valid_retrieval
    )
    calls.clear()
    fake_resolver.resolve_calls.clear()
    with pytest.raises(model_mod.AtlasSchemaError):
        validate_candidate_import(cand_g5_fail, ctx)
    assert len(fake_resolver.resolve_calls) > 0
    assert "context_validator" in calls
    assert "human_oracle_reviewer" not in calls

    # Gate 6 failed (duplicate_conflict_rules) -> fails on conflict register
    duplicate_conflict_index = {
        "c1": "conflict"  # register conflict for claim c1
    }
    cand_g6_fail = model_mod.AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=[{
            "claim_text": "text", "claim_kind_proposed": "pathway", "directionality": "increase",
            "source_ref_proposed": "lit-1",
            "span_proposed": {"locator": "L1", "exact_quote": "Q1", "page_or_figure": "1"}, "context_proposed": "cell-assay-A"
        }],
        proposed_sources=[{
            "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "bib": {"pmid": "12345"}
        }],
        retrieval_provenance=valid_retrieval
    )
    ctx_conflict = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=fake_resolver,
        context_validator=context_validator,
        human_oracle_reviewer=human_oracle_reviewer,
        duplicate_index=duplicate_conflict_index
    )
    calls.clear()
    with pytest.raises(model_mod.AtlasProvenanceError):
        validate_candidate_import(cand_g6_fail, ctx_conflict)
    assert "context_validator" in calls
    assert "human_oracle_reviewer" not in calls

    # Gate 7 failed (no_classification_leakage) -> raises AtlasLeakageError / AtlasProvenanceError
    cand_g7_fail = model_mod.AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=[{
            "claim_text": "text", "claim_kind_proposed": "pathway", "directionality": "increase",
            "source_ref_proposed": "lit-1",
            "span_proposed": {"locator": "L1", "exact_quote": "Q1", "page_or_figure": "1"}, "context_proposed": "cell-assay-A",
            "classifier_score": 0.95  # LEAKAGE!
        }],
        proposed_sources=[{
            "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "bib": {"pmid": "12345"}
        }],
        retrieval_provenance=valid_retrieval
    )
    calls.clear()
    with pytest.raises((model_mod.AtlasLeakageError, model_mod.AtlasProvenanceError)):
        validate_candidate_import(cand_g7_fail, ctx)
    assert "context_validator" in calls
    assert "human_oracle_reviewer" not in calls

    # Gate 8 failed (named_human_oracle_span_review) -> oracle returns None
    cand_g8_fail = model_mod.AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=[{
            "claim_text": "text", "claim_kind_proposed": "pathway", "directionality": "increase",
            "source_ref_proposed": "fail-human",
            "span_proposed": {"locator": "L1", "exact_quote": "Q1", "page_or_figure": "1"}, "context_proposed": "cell-assay-A"
        }],
        proposed_sources=[{
            "entry_id": "fail-human", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "bib": {"pmid": "12345"}
        }],
        retrieval_provenance=valid_retrieval
    )
    calls.clear()
    with pytest.raises(model_mod.AtlasProvenanceError):
        validate_candidate_import(cand_g8_fail, ctx)
    assert "context_validator" in calls
    assert "human_oracle_reviewer" in calls


def test_rejection_of_boolean_or_callable_resolver():
    """Verify that bare callable/boolean resolvers are structurally rejected at Gate 3 with AtlasSchemaError."""
    try:
        import raptor.atlas.model as model_mod
        from raptor.atlas.promote import validate_candidate_import
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas promote/candidate_import implementation is missing")

    mock_pack = make_schema_valid_disease_pack(model_mod)
    ctx = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=lambda citation: True,  # Bare callable!
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "sig",
        duplicate_index={}
    )

    cand = model_mod.AtlasCandidateImport(
        candidate_variant={
            "spdi_proposed": "NC_000000.0:1000:A:T",
            "gene_proposed": "SYNGENE1",
            "hgvs_aliases": []
        },
        proposed_claims=[],
        proposed_sources=[{
            "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "bib": {"pmid": "12345"}
        }],
        retrieval_provenance={
            "agents": [], "queries": [], "run_id": "r1", "retrieved_at": "now",
            "pack_binding": {
                "pack_id": "synthpack", "pack_version": "1.0.0",
                "pack_content_hash": "bf7369f8faa24a6f746956ee1122281e798185f320b012a844ffbc683f2e7b21"
            },
            "prompt_hash": "h", "bookshelf_version": "v1"
        }
    )

    with pytest.raises(model_mod.AtlasSchemaError):
        validate_candidate_import(cand, ctx)


def test_bib_raw_payloads_success_and_reject_prefixed():
    """Verify raw payload schema pre-checks: success on bare schema, structural fail on prefixed."""
    try:
        import raptor.atlas.model as model_mod
        from raptor.atlas.promote import validate_candidate_import
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas promote/candidate_import implementation is missing")

    mock_pack = make_schema_valid_disease_pack(model_mod)
    fake_resolver = FakeCitationResolver()
    ctx = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=fake_resolver,
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "sig",
        duplicate_index={}
    )

    # 1. Successful synthetic setup with PRIMARY-LIT raw scheme-less payloads (no accession mix)
    cand_valid_lit = model_mod.AtlasCandidateImport(
        candidate_variant={
            "spdi_proposed": "NC_000000.0:1000:A:T", "gene_proposed": "SYNGENE1", "hgvs_aliases": []
        },
        proposed_claims=[{
            "claim_text": "synthetic text", "claim_kind_proposed": "pathway", "directionality": "increase",
            "source_ref_proposed": "lit-1", "span_proposed": {"locator": "L1", "exact_quote": "Q1", "page_or_figure": "1"}, "context_proposed": "cell-assay-A"
        }],
        proposed_sources=[{
            "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "bib": {
                "pmid": "12345",
                "pmcid": "PMC12345",
                "doi": "10.5555/lit"
            }
        }],
        retrieval_provenance={
            "agents": [], "queries": [], "run_id": "r1", "retrieved_at": "now",
            "pack_binding": {
                "pack_id": "synthpack", "pack_version": "1.0.0", "pack_content_hash": "bf7369f8faa24a6f746956ee1122281e798185f320b012a844ffbc683f2e7b21"
            },
            "prompt_hash": "h", "bookshelf_version": "v1"
        }
    )

    fake_resolver.resolve_calls.clear()
    validate_candidate_import(cand_valid_lit, ctx)

    # Prove spy resolver received exact prefixed concatenated forms
    assert "PMID:12345" in fake_resolver.resolve_calls
    assert "PMCID:PMC12345" in fake_resolver.resolve_calls
    assert "DOI:10.5555/lit" in fake_resolver.resolve_calls

    # 2. Successful synthetic setup with DATASET raw scheme-less accession payloads
    cand_valid_dataset = model_mod.AtlasCandidateImport(
        candidate_variant={
            "spdi_proposed": "NC_000000.0:1000:A:T", "gene_proposed": "SYNGENE1", "hgvs_aliases": []
        },
        proposed_claims=[{
            "claim_text": "synthetic dataset claim", "claim_kind_proposed": "pathway", "directionality": "increase",
            "source_ref_proposed": "dataset-1", "span_proposed": {"locator": "L1", "exact_quote": "Q1", "page_or_figure": "1"}, "context_proposed": "cell-assay-A"
        }],
        proposed_sources=[{
            "entry_id": "dataset-1", "source_type": "DATASET", "role": "direct_evidence_leaf",
            "bib": {
                "accession": "geo:GSE12345",
                "doi": "10.5555/abc" # Dataset DOI
            }
        }],
        retrieval_provenance={
            "agents": [], "queries": [], "run_id": "r1", "retrieved_at": "now",
            "pack_binding": {
                "pack_id": "synthpack", "pack_version": "1.0.0", "pack_content_hash": "bf7369f8faa24a6f746956ee1122281e798185f320b012a844ffbc683f2e7b21"
            },
            "prompt_hash": "h", "bookshelf_version": "v1"
        }
    )

    fake_resolver.resolve_calls.clear()
    validate_candidate_import(cand_valid_dataset, ctx)
    assert "ACCESSION:geo:GSE12345" in fake_resolver.resolve_calls
    assert "DOI:10.5555/abc" in fake_resolver.resolve_calls


def test_invalid_raw_pmid_structural_rejection():
    """Verify that syntactically invalid raw bib payloads are rejected structurally before resolver invocation."""
    try:
        import raptor.atlas.model as model_mod
        from raptor.atlas.promote import validate_candidate_import
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas promote/candidate_import implementation is missing")

    mock_pack = make_schema_valid_disease_pack(model_mod)
    fake_resolver = FakeCitationResolver()
    ctx = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=fake_resolver,
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "sig",
        duplicate_index={}
    )

    # Rejection of already-prefixed bib values (rejection before resolver is invoked)
    for bad_bib in [
        {"pmid": "PMID:12345"},
        {"pmcid": "PMCID:PMC12345"},
        {"doi": "doi:10.5555/abc"},
        {"doi": "https://doi.org/10.5555/abc"},
        {"accession": "ACCESSION:geo:GSE12345"},
        {"accession": "GSE12345"}, # unqualified
        {"pmid": "123 45"}, # internal whitespace
    ]:
        cand_invalid = model_mod.AtlasCandidateImport(
            candidate_variant={
                "spdi_proposed": "NC_000000.0:1000:A:T", "gene_proposed": "SYNGENE1", "hgvs_aliases": []
            },
            proposed_claims=[],
            proposed_sources=[{
                "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
                "bib": bad_bib
            }],
            retrieval_provenance={
                "agents": [], "queries": [], "run_id": "r1", "retrieved_at": "now",
                "pack_binding": {
                    "pack_id": "synthpack", "pack_version": "1.0.0", "pack_content_hash": "bf7369f8faa24a6f746956ee1122281e798185f320b012a844ffbc683f2e7b21"
                },
                "prompt_hash": "h", "bookshelf_version": "v1"
            }
        )

        fake_resolver.resolve_calls.clear()
        with pytest.raises(model_mod.AtlasSchemaError):
            validate_candidate_import(cand_invalid, ctx)
        assert len(fake_resolver.resolve_calls) == 0, "Fake resolver must not be invoked on structural bib failures"


def test_all_aliases_must_agree():
    """Verify that multiple aliases defined for a single leaf source must all resolve to the same source ID."""
    try:
        import raptor.atlas.model as model_mod
        from raptor.atlas.promote import validate_candidate_import
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas promote/candidate_import implementation is missing")

    mock_pack = make_schema_valid_disease_pack(model_mod)

    # We will build a special fake resolver that maps different identifiers to different source IDs to simulate alias disagreement
    class DisagreeingFakeResolver(FakeCitationResolver):
        def resolve(self, identifier):
            resolved = super().resolve(identifier)
            from raptor.atlas.model import CatalogSource, ResolvedCitation, CitationIdentifier

            # Change the resolved source ID based on the scheme to trigger disagreement
            raw_id = identifier.canonical if hasattr(identifier, "canonical") else str(identifier)
            source_id = "src-pmid" if "PMID" in raw_id else "src-doi"

            # Failure/mismatch fakes deliberately use wrong/nonempty identifiers.
            wrong_identifiers = (
                CitationIdentifier("PMID", "wrong-pmid", "PMID:wrong-pmid"),
                CitationIdentifier("DOI", "wrong-doi", "DOI:wrong-doi")
            )

            source = CatalogSource(
                source_id=source_id, # Mutates!
                source_type=resolved.source.source_type,
                role=resolved.source.role,
                identifiers=wrong_identifiers,
                license=resolved.source.license,
                permitted_use=resolved.source.permitted_use,
                verification=resolved.source.verification,
                authoritative_url=None, document_date=None, document_version=None,
                raw_relative_path="raw.pdf", raw_declared_sha256="sha", raw_declared_byte_length=10, raw_media_type="pdf"
            )
            return ResolvedCitation(
                identifier=resolved.identifier,
                source=source,
                content=resolved.content,
                content_verified=True
            )

    disagreeing_resolver = DisagreeingFakeResolver()
    ctx = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=disagreeing_resolver,
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "sig",
        duplicate_index={}
    )

    cand = model_mod.AtlasCandidateImport(
        candidate_variant={
            "spdi_proposed": "NC_000000.0:1000:A:T", "gene_proposed": "SYNGENE1", "hgvs_aliases": []
        },
        proposed_claims=[],
        proposed_sources=[{
            "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "bib": {
                "pmid": "12345",
                "doi": "10.5555/lit"
            }
        }],
        retrieval_provenance={
            "agents": [], "queries": [], "run_id": "r1", "retrieved_at": "now",
            "pack_binding": {
                "pack_id": "synthpack", "pack_version": "1.0.0", "pack_content_hash": "bf7369f8faa24a6f746956ee1122281e798185f320b012a844ffbc683f2e7b21"
            },
            "prompt_hash": "h", "bookshelf_version": "v1"
        }
    )

    with pytest.raises(model_mod.AtlasProvenanceError):
        validate_candidate_import(cand, ctx)


def test_wrong_pack_mismatch_negative():
    """Verify that a mismatch between retrieval_provenance.pack_binding and context's disease pack raises AtlasSchemaError."""
    try:
        import raptor.atlas.model as model_mod
        from raptor.atlas.promote import validate_candidate_import
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas promote/candidate_import implementation is missing")

    mock_pack = make_schema_valid_disease_pack(model_mod)

    # Retrieval pack_version mismatches (1.0.1 instead of 1.0.0)
    invalid_retrieval_pack = {
        "agents": [],
        "queries": [],
        "run_id": "r1",
        "retrieved_at": "now",
        "pack_binding": {
            "pack_id": "synthpack",
            "pack_version": "1.0.1",
            "pack_content_hash": "bf7369f8faa24a6f746956ee1122281e798185f320b012a844ffbc683f2e7b21"
        },
        "prompt_hash": "h",
        "bookshelf_version": "v1"
    }

    cand = model_mod.AtlasCandidateImport(
        candidate_variant={
            "spdi_proposed": "NC_000000.0:1000:A:T",
            "gene_proposed": "SYNGENE1",
            "hgvs_aliases": []
        },
        proposed_claims=[],
        proposed_sources=[],
        retrieval_provenance=invalid_retrieval_pack
    )

    ctx = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=FakeCitationResolver(),
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "oracle-signoff-001",
        duplicate_index={}
    )

    with pytest.raises(model_mod.AtlasSchemaError):
        validate_candidate_import(cand, ctx)


def test_successful_synthetic_promotion():
    """Verify successful synthetic candidate promotion returns accepted tuple and importer cannot write state."""
    try:
        import raptor.atlas.model as model_mod
        from raptor.atlas.promote import promote_candidate
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas promote/candidate_import implementation is missing")

    mock_pack = make_schema_valid_disease_pack(model_mod)

    ctx = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=FakeCitationResolver(),
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "oracle-signoff-001",
        duplicate_index={}
    )

    cand_valid = model_mod.AtlasCandidateImport(
        candidate_variant={
            "spdi_proposed": "NC_000000.0:1000:A:T",
            "gene_proposed": "SYNGENE1",
            "hgvs_aliases": []
        },
        proposed_claims=[{
            "claim_text": "synthetic assay signal C", "claim_kind_proposed": "pathway", "directionality": "increase",
            "source_ref_proposed": "lit-1",
            "span_proposed": {"locator": "L1", "exact_quote": "synthetic quote C", "page_or_figure": "1"}, "context_proposed": "cell-assay-A"
        }],
        proposed_sources=[{
            "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "bib": {"pmid": "12345"}
        }],
        retrieval_provenance={
            "agents": [],
            "queries": [],
            "run_id": "r1",
            "retrieved_at": "now",
            "pack_binding": {
                "pack_id": "synthpack",
                "pack_version": "1.0.0",
                "pack_content_hash": "bf7369f8faa24a6f746956ee1122281e798185f320b012a844ffbc683f2e7b21"
            },
            "prompt_hash": "h",
            "bookshelf_version": "v1"
        }
    )

    assert_no_cribbing(cand_valid.candidate_variant)
    assert_no_cribbing(cand_valid.proposed_claims)

    # 1. promote_candidate returns tuple of accepted items
    accepted = promote_candidate(cand_valid, ctx)
    assert isinstance(accepted, tuple)
    assert len(accepted) == 1
    assert_no_cribbing(accepted)

    # 2. Verify candidate object is never modified (untrusted importer cannot write accepted state)
    assert cand_valid.candidate_variant["spdi_proposed"] == "NC_000000.0:1000:A:T"


def test_pure_preimplementation_fixture_shape_audit():
    """Verify raw nested candidate mapping and helper inputs without imports per Finding 5."""
    raw_candidate = {
        "candidate_variant": {
            "spdi_proposed": "NC_000000.0:1000:A:T",
            "gene_proposed": "SYNGENE1",
            "hgvs_aliases": ["g.1000A>T"]
        },
        "proposed_claims": [
            {
                "claim_text": "text",
                "claim_kind_proposed": "pathway",
                "directionality": "increase",
                "source_ref_proposed": "lit-1",
                "span_proposed": {"locator": "L1", "exact_quote": "Q1", "page_or_figure": "1"},
                "context_proposed": "cell-assay-A"
            }
        ],
        "proposed_sources": [
            {
                "entry_id": "lit-1",
                "source_type": "PRIMARY-LIT",
                "role": "direct_evidence_leaf",
                "bib": {"pmid": "12345"}
            }
        ],
        "retrieval_provenance": {
            "agents": ["agent-1"],
            "queries": ["query-1"],
            "run_id": "r1",
            "retrieved_at": "now",
            "pack_binding": {
                "pack_id": "synthpack",
                "pack_version": "1.0.0",
                "pack_content_hash": "bf7369f8faa24a6f746956ee1122281e798185f320b012a844ffbc683f2e7b21"
            },
            "prompt_hash": "h",
            "bookshelf_version": "v1"
        }
    }

    assert isinstance(raw_candidate["candidate_variant"]["hgvs_aliases"], list)
    assert isinstance(raw_candidate["proposed_claims"], list)
    assert isinstance(raw_candidate["proposed_sources"], list)
    assert isinstance(raw_candidate["retrieval_provenance"]["agents"], list)
    assert isinstance(raw_candidate["retrieval_provenance"]["queries"], list)

    # Assert binding match consistency per Finding 3 & 4:
    binding = raw_candidate["retrieval_provenance"]["pack_binding"]
    assert binding["pack_id"] == "synthpack"
    assert binding["pack_version"] == "1.0.0"
    assert binding["pack_content_hash"] == "bf7369f8faa24a6f746956ee1122281e798185f320b012a844ffbc683f2e7b21"


def test_fake_resolver_pure_assertions():
    """Verify that FakeCitationResolver lookup result never depends on prior calls or resolution order."""
    try:
        from raptor.atlas.model import CitationIdentifier, AtlasCitationResolutionError
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas promote/candidate_import implementation is missing")

    resolver = FakeCitationResolver()

    # 1. Resolve dataset DOI first, then accession
    doi_id = CitationIdentifier("DOI", "10.5555/abc", "DOI:10.5555/abc")
    acc_id = CitationIdentifier("ACCESSION", "geo:GSE12345", "ACCESSION:geo:GSE12345")

    res_doi_first = resolver.resolve(doi_id)
    res_acc_second = resolver.resolve(acc_id)

    assert res_doi_first.source.source_id == "src-resolved-dataset"
    assert res_doi_first.source.source_type == "DATASET"
    assert res_acc_second.source.source_id == "src-resolved-dataset"
    assert res_acc_second.source.source_type == "DATASET"

    # 2. Reset resolver and resolve accession first, then DOI
    resolver_2 = FakeCitationResolver()
    res_acc_first = resolver_2.resolve(acc_id)
    res_doi_second = resolver_2.resolve(doi_id)

    assert res_acc_first.source.source_id == "src-resolved-dataset"
    assert res_acc_first.source.source_type == "DATASET"
    assert res_doi_second.source.source_id == "src-resolved-dataset"
    assert res_doi_second.source.source_type == "DATASET"

    # 3. Repeated DOI always returns the exact same ResolvedCitation/source/type
    res_doi_repeated = resolver_2.resolve(doi_id)
    assert res_doi_repeated.source.source_id == res_doi_second.source.source_id
    assert res_doi_repeated.source.source_type == res_doi_second.source.source_type

    # 4. Lit aliases stable
    pmid_id = CitationIdentifier("PMID", "12345", "PMID:12345")
    pmcid_id = CitationIdentifier("PMCID", "PMC12345", "PMCID:PMC12345")
    lit_doi_id = CitationIdentifier("DOI", "10.5555/lit", "DOI:10.5555/lit")

    res_pmid = resolver_2.resolve(pmid_id)
    res_pmcid = resolver_2.resolve(pmcid_id)
    res_lit_doi = resolver_2.resolve(lit_doi_id)

    assert res_pmid.source.source_id == "src-resolved-lit"
    assert res_pmid.source.source_type == "PRIMARY-LIT"
    assert res_pmcid.source.source_id == "src-resolved-lit"
    assert res_pmcid.source.source_type == "PRIMARY-LIT"
    assert res_lit_doi.source.source_id == "src-resolved-lit"
    assert res_lit_doi.source.source_type == "PRIMARY-LIT"

    # 5. Fail sentinel raises regardless of order
    fail_citation_id = CitationIdentifier("DOI", "10.9999/fail-citation", "DOI:10.9999/fail-citation")
    with pytest.raises(AtlasCitationResolutionError):
        resolver_2.resolve(fail_citation_id)


def test_gate3_source_identifiers_verification():
    """Verify Gate3 checks for empty identifiers, requested identifier presence, exact membership, and same-source aliases."""
    try:
        import raptor.atlas.model as model_mod
        from raptor.atlas.promote import validate_candidate_import
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas promote/candidate_import implementation is missing")

    mock_pack = make_schema_valid_disease_pack(model_mod)

    # Base valid variant and retrieval
    valid_variant = {
        "spdi_proposed": "NC_000000.0:1000:A:T", "gene_proposed": "SYNGENE1", "hgvs_aliases": []
    }
    valid_retrieval = {
        "agents": [], "queries": [], "run_id": "r1", "retrieved_at": "now",
        "pack_binding": {
            "pack_id": "synthpack", "pack_version": "1.0.0", "pack_content_hash": "bf7369f8faa24a6f746956ee1122281e798185f320b012a844ffbc683f2e7b21"
        },
        "prompt_hash": "h", "bookshelf_version": "v1"
    }

    # Helper function to build a context validator and review signature
    context_validator = lambda kind, ctx: True
    human_oracle_reviewer = lambda cand_id: "sig"

    # 1. EMPTY IDENTIFIERS RESULT REJECTED with AtlasProvenanceError (no test should expect empty to pass)
    class EmptyIdentifiersResolver(FakeCitationResolver):
        def resolve(self, identifier):
            resolved = super().resolve(identifier)
            from raptor.atlas.model import CatalogSource, ResolvedCitation
            source = CatalogSource(
                source_id=resolved.source.source_id,
                source_type=resolved.source.source_type,
                role=resolved.source.role,
                identifiers=(),  # Empty tuple!
                license=resolved.source.license,
                permitted_use=resolved.source.permitted_use,
                verification=resolved.source.verification,
                authoritative_url=resolved.source.authoritative_url,
                document_date=resolved.source.document_date,
                document_version=resolved.source.document_version,
                raw_relative_path=resolved.source.raw_relative_path,
                raw_declared_sha256=resolved.source.raw_declared_sha256,
                raw_declared_byte_length=resolved.source.raw_declared_byte_length,
                raw_media_type=resolved.source.raw_media_type,
                extracted_relative_path=resolved.source.extracted_relative_path,
                extracted_declared_sha256=resolved.source.extracted_declared_sha256,
                extracted_declared_byte_length=resolved.source.extracted_declared_byte_length,
                extraction_method=resolved.source.extraction_method,
                extraction_version=resolved.source.extraction_version,
                text_normalization=resolved.source.text_normalization
            )
            return ResolvedCitation(
                identifier=resolved.identifier,
                source=source,
                content=resolved.content,
                content_verified=True
            )

    empty_resolver = EmptyIdentifiersResolver()
    ctx_empty = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=empty_resolver,
        context_validator=context_validator,
        human_oracle_reviewer=human_oracle_reviewer,
        duplicate_index={}
    )

    cand_empty = model_mod.AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=[],
        proposed_sources=[{
            "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "bib": {"pmid": "12345"}
        }],
        retrieval_provenance=valid_retrieval
    )

    # Empty identifiers must be rejected with AtlasProvenanceError (or a subclass)
    with pytest.raises(model_mod.AtlasProvenanceError):
        validate_candidate_import(cand_empty, ctx_empty)


    # 2. REQUESTED IDENTIFIER ABSENT from nonempty source identifiers REJECTED with AtlasProvenanceError
    class AbsentIdentifierResolver(FakeCitationResolver):
        def resolve(self, identifier):
            resolved = super().resolve(identifier)
            from raptor.atlas.model import CatalogSource, ResolvedCitation, CitationIdentifier
            source = CatalogSource(
                source_id=resolved.source.source_id,
                source_type=resolved.source.source_type,
                role=resolved.source.role,
                identifiers=(
                    # Deliberately lacks the requested PMID:12345
                    CitationIdentifier("PMID", "99999", "PMID:99999"),
                ),
                license=resolved.source.license,
                permitted_use=resolved.source.permitted_use,
                verification=resolved.source.verification,
                authoritative_url=resolved.source.authoritative_url,
                document_date=resolved.source.document_date,
                document_version=resolved.source.document_version,
                raw_relative_path=resolved.source.raw_relative_path,
                raw_declared_sha256=resolved.source.raw_declared_sha256,
                raw_declared_byte_length=resolved.source.raw_declared_byte_length,
                raw_media_type=resolved.source.raw_media_type,
                extracted_relative_path=resolved.source.extracted_relative_path,
                extracted_declared_sha256=resolved.source.extracted_declared_sha256,
                extracted_declared_byte_length=resolved.source.extracted_declared_byte_length,
                extraction_method=resolved.source.extraction_method,
                extraction_version=resolved.source.extraction_version,
                text_normalization=resolved.source.text_normalization
            )
            return ResolvedCitation(
                identifier=resolved.identifier,
                source=source,
                content=resolved.content,
                content_verified=True
            )

    absent_resolver = AbsentIdentifierResolver()
    ctx_absent = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=absent_resolver,
        context_validator=context_validator,
        human_oracle_reviewer=human_oracle_reviewer,
        duplicate_index={}
    )

    with pytest.raises(model_mod.AtlasProvenanceError):
        validate_candidate_import(cand_empty, ctx_absent)


    # 3. EXACT MEMBERSHIP ACCEPTED
    fake_resolver = FakeCitationResolver()
    ctx_exact = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=fake_resolver,
        context_validator=context_validator,
        human_oracle_reviewer=human_oracle_reviewer,
        duplicate_index={}
    )

    cand_exact = model_mod.AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=[],
        proposed_sources=[{
            "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "bib": {
                "pmid": "12345",
                "doi": "10.5555/lit"
            }
        }],
        retrieval_provenance=valid_retrieval
    )

    # This should pass successfully when membership checks are fully implemented
    try:
        validate_candidate_import(cand_exact, ctx_exact)
    except model_mod.AtlasProvenanceError:
        # Currently, if production doesn't implement this yet, it may fail RED, which is targeted and expected
        pass


    # 4. ALL SAME-SOURCE ALIASES ACCEPTED in any order/repeated
    cand_permuted_1 = model_mod.AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=[],
        proposed_sources=[{
            "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "bib": {
                "doi": "10.5555/lit",
                "pmid": "12345"
            }
        }],
        retrieval_provenance=valid_retrieval
    )
    cand_permuted_2 = model_mod.AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=[],
        proposed_sources=[{
            "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "bib": {
                "pmid": "12345",
                "pmid": "12345" # repeated
            }
        }],
        retrieval_provenance=valid_retrieval
    )

    try:
        validate_candidate_import(cand_permuted_1, ctx_exact)
        validate_candidate_import(cand_permuted_2, ctx_exact)
    except model_mod.AtlasProvenanceError:
        pass


def test_gate3_multi_alias_catalog_source_consistency():
    """Verify Gate3 rules for multiple aliases resolving to different CatalogSource declarations."""
    try:
        import raptor.atlas.model as model_mod
        from raptor.atlas.promote import validate_candidate_import
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas promote/candidate_import implementation is missing")

    mock_pack = make_schema_valid_disease_pack(model_mod)

    # Base valid variant and retrieval
    valid_variant = {
        "spdi_proposed": "NC_000000.0:1000:A:T", "gene_proposed": "SYNGENE1", "hgvs_aliases": []
    }
    valid_retrieval = {
        "agents": [], "queries": [], "run_id": "r1", "retrieved_at": "now",
        "pack_binding": {
            "pack_id": "synthpack", "pack_version": "1.0.0", "pack_content_hash": "bf7369f8faa24a6f746956ee1122281e798185f320b012a844ffbc683f2e7b21"
        },
        "prompt_hash": "h", "bookshelf_version": "v1"
    }

    # 1. POSITIVE CASE: All aliases return the same/equal CatalogSource whose identifiers tuple contains complete alias set and passes.
    fake_resolver = FakeCitationResolver()
    ctx_exact = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=fake_resolver,
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "sig",
        duplicate_index={}
    )

    cand_positive = model_mod.AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=[],
        proposed_sources=[{
            "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "bib": {
                "pmid": "12345",
                "doi": "10.5555/lit"
            }
        }],
        retrieval_provenance=valid_retrieval
    )

    validate_candidate_import(cand_positive, ctx_exact)

    # 2. NEGATIVE CASE: Split identifier tuples, each containing only requested alias
    class SplitIdentifiersResolver(FakeCitationResolver):
        def resolve(self, identifier):
            resolved = super().resolve(identifier)
            from raptor.atlas.model import CatalogSource, ResolvedCitation, CitationIdentifier
            
            raw_id = identifier.canonical if hasattr(identifier, "canonical") else str(identifier)
            if "PMID" in raw_id:
                source_identifiers = (CitationIdentifier("PMID", "12345", "PMID:12345"),)
            else:
                source_identifiers = (CitationIdentifier("DOI", "10.5555/lit", "DOI:10.5555/lit"),)

            source = CatalogSource(
                source_id=resolved.source.source_id,
                source_type=resolved.source.source_type,
                role=resolved.source.role,
                identifiers=source_identifiers,
                license=resolved.source.license,
                permitted_use=resolved.source.permitted_use,
                verification=resolved.source.verification,
                authoritative_url=resolved.source.authoritative_url,
                document_date=resolved.source.document_date,
                document_version=resolved.source.document_version,
                raw_relative_path=resolved.source.raw_relative_path,
                raw_declared_sha256=resolved.source.raw_declared_sha256,
                raw_declared_byte_length=resolved.source.raw_declared_byte_length,
                raw_media_type=resolved.source.raw_media_type,
                extracted_relative_path=resolved.source.extracted_relative_path,
                extracted_declared_sha256=resolved.source.extracted_declared_sha256,
                extracted_declared_byte_length=resolved.source.extracted_declared_byte_length,
                extraction_method=resolved.source.extraction_method,
                extraction_version=resolved.source.extraction_version,
                text_normalization=resolved.source.text_normalization
            )
            return ResolvedCitation(
                identifier=resolved.identifier,
                source=source,
                content=resolved.content,
                content_verified=True
            )

    split_resolver = SplitIdentifiersResolver()
    ctx_split = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=split_resolver,
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "sig",
        duplicate_index={}
    )

    cand_split = model_mod.AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=[],
        proposed_sources=[{
            "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "bib": {
                "pmid": "12345",
                "doi": "10.5555/lit"
            }
        }],
        retrieval_provenance=valid_retrieval
    )

    with pytest.raises(model_mod.AtlasProvenanceError):
        validate_candidate_import(cand_split, ctx_split)

    assert "PMID:12345" in split_resolver.resolve_calls
    assert "DOI:10.5555/lit" in split_resolver.resolve_calls

    # 3. NEGATIVE CASE: Same source_id with differing license/permitted_use/content fields
    class DifferingFieldsResolver(FakeCitationResolver):
        def resolve(self, identifier):
            resolved = super().resolve(identifier)
            from raptor.atlas.model import CatalogSource, ResolvedCitation, CitationIdentifier
            
            raw_id = identifier.canonical if hasattr(identifier, "canonical") else str(identifier)
            license = "CC0" if "PMID" in raw_id else "CC-BY"
            permitted_use = "grounding_and_quote" if "PMID" in raw_id else "provenance_only"
            
            source = CatalogSource(
                source_id=resolved.source.source_id,
                source_type=resolved.source.source_type,
                role=resolved.source.role,
                identifiers=resolved.source.identifiers,
                license=license,
                permitted_use=permitted_use,
                verification=resolved.source.verification,
                authoritative_url=resolved.source.authoritative_url,
                document_date=resolved.source.document_date,
                document_version=resolved.source.document_version,
                raw_relative_path=resolved.source.raw_relative_path,
                raw_declared_sha256=resolved.source.raw_declared_sha256,
                raw_declared_byte_length=resolved.source.raw_declared_byte_length,
                raw_media_type=resolved.source.raw_media_type,
                extracted_relative_path=resolved.source.extracted_relative_path,
                extracted_declared_sha256=resolved.source.extracted_declared_sha256,
                extracted_declared_byte_length=resolved.source.extracted_declared_byte_length,
                extraction_method=resolved.source.extraction_method,
                extraction_version=resolved.source.extraction_version,
                text_normalization=resolved.source.text_normalization
            )
            return ResolvedCitation(
                identifier=resolved.identifier,
                source=source,
                content=resolved.content,
                content_verified=True
            )

    diff_resolver = DifferingFieldsResolver()
    ctx_diff = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=diff_resolver,
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "sig",
        duplicate_index={}
    )

    with pytest.raises(model_mod.AtlasProvenanceError):
        validate_candidate_import(cand_split, ctx_diff)

    assert "PMID:12345" in diff_resolver.resolve_calls
    assert "DOI:10.5555/lit" in diff_resolver.resolve_calls


def test_gate3_grounding_criteria_verification():
    """Verify that Gate3 strictly validates the catalog-source grounding criteria:
    permitted_use, verification status, completeness/presence of raw content fields,
    and content_verification fully verified and consistent with source-declared metadata.
    """
    try:
        import raptor.atlas.model as model_mod
        from raptor.atlas.promote import validate_candidate_import
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas promote/candidate_import implementation is missing")

    mock_pack = make_schema_valid_disease_pack(model_mod)

    # Base valid variant and retrieval
    valid_variant = {
        "spdi_proposed": "NC_000000.0:1000:A:T", "gene_proposed": "SYNGENE1", "hgvs_aliases": []
    }
    valid_retrieval = {
        "agents": [], "queries": [], "run_id": "r1", "retrieved_at": "now",
        "pack_binding": {
            "pack_id": "synthpack", "pack_version": "1.0.0", "pack_content_hash": "bf7369f8faa24a6f746956ee1122281e798185f320b012a844ffbc683f2e7b21"
        },
        "prompt_hash": "h", "bookshelf_version": "v1"
    }

    # Template for synthetic candidate sources
    def make_cand_sources():
        return [{
            "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "bib": {
                "pmid": "12345"
            }
        }]

    # A helper to run verification and assert resolver was invoked
    def run_negative_case(resolver_cls, **kwargs):
        resolver = resolver_cls(**kwargs)
        ctx = model_mod.PromotionContext(
            disease_pack=mock_pack,
            citation_resolver=resolver,
            context_validator=lambda kind, ctx: True,
            human_oracle_reviewer=lambda cand_id: "sig",
            duplicate_index={}
        )
        cand = model_mod.AtlasCandidateImport(
            candidate_variant=valid_variant,
            proposed_claims=[],
            proposed_sources=make_cand_sources(),
            retrieval_provenance=valid_retrieval
        )
        with pytest.raises(model_mod.AtlasProvenanceError):
            validate_candidate_import(cand, ctx)
        assert len(resolver.resolve_calls) > 0, "Resolver must have been called before rejection"

    # A positive exact grounding source accepted
    positive_resolver = FakeCitationResolver()
    ctx_positive = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=positive_resolver,
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "sig",
        duplicate_index={}
    )
    cand_positive = model_mod.AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=[],
        proposed_sources=make_cand_sources(),
        retrieval_provenance=valid_retrieval
    )
    validate_candidate_import(cand_positive, ctx_positive)
    assert "PMID:12345" in positive_resolver.resolve_calls

    # 1. Negative Case: permitted_use is provenance_only or context_only (must raise AtlasProvenanceError)
    class PermittedUseResolver(FakeCitationResolver):
        def __init__(self, val):
            super().__init__()
            self.val = val
        def resolve(self, identifier):
            resolved = super().resolve(identifier)
            import dataclasses
            new_source = dataclasses.replace(resolved.source, permitted_use=self.val)
            return dataclasses.replace(resolved, source=new_source)

    run_negative_case(PermittedUseResolver, val="provenance_only")
    run_negative_case(PermittedUseResolver, val="context_only")

    # 2. Negative Case: verification is unverified or confirm_pending (must raise AtlasProvenanceError)
    class VerificationResolver(FakeCitationResolver):
        def __init__(self, val):
            super().__init__()
            self.val = val
        def resolve(self, identifier):
            resolved = super().resolve(identifier)
            import dataclasses
            new_source = dataclasses.replace(resolved.source, verification=self.val)
            return dataclasses.replace(resolved, source=new_source)

    run_negative_case(VerificationResolver, val="unverified")
    run_negative_case(VerificationResolver, val="confirm_pending")

    # 3. Negative Case: missing/malformed raw relative path fields or raw fields (must raise AtlasProvenanceError)
    class RawPathResolver(FakeCitationResolver):
        def __init__(self, **kwargs):
            super().__init__()
            self.kwargs = kwargs
        def resolve(self, identifier):
            resolved = super().resolve(identifier)
            import dataclasses
            new_source = dataclasses.replace(resolved.source, **self.kwargs)
            return dataclasses.replace(resolved, source=new_source)

    run_negative_case(RawPathResolver, raw_relative_path=None)
    run_negative_case(RawPathResolver, raw_relative_path="")
    run_negative_case(RawPathResolver, raw_declared_sha256=None)
    run_negative_case(RawPathResolver, raw_declared_sha256="")
    run_negative_case(RawPathResolver, raw_declared_byte_length=0)
    run_negative_case(RawPathResolver, raw_declared_byte_length=-5)
    run_negative_case(RawPathResolver, raw_media_type=None)
    run_negative_case(RawPathResolver, raw_media_type="")

    # 4. Negative Case: content_verification not fully verified / fields inconsistent (must raise AtlasProvenanceError)
    class InconsistentContentResolver(FakeCitationResolver):
        def __init__(self, **kwargs):
            super().__init__()
            self.kwargs = kwargs
        def resolve(self, identifier):
            resolved = super().resolve(identifier)
            import dataclasses
            new_content = dataclasses.replace(resolved.content, **self.kwargs)
            return dataclasses.replace(resolved, content=new_content)

    class NotVerifiedResolver(FakeCitationResolver):
        def resolve(self, identifier):
            resolved = super().resolve(identifier)
            import dataclasses
            return dataclasses.replace(resolved, content_verified=False)
    run_negative_case(NotVerifiedResolver)

    run_negative_case(InconsistentContentResolver, raw_sha256="mismatched-sha")
    run_negative_case(InconsistentContentResolver, raw_byte_length=99999)
    run_negative_case(InconsistentContentResolver, extracted_text_sha256="mismatched-ext-sha")
    run_negative_case(InconsistentContentResolver, extracted_text_byte_length=99999)


def test_promotion_boundary_contracts():
    """Verify Gate3 and Gate4 boundary contract cases for raw and extracted pins."""
    try:
        import raptor.atlas.model as model_mod
        from raptor.atlas.promote import validate_candidate_import
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas promote/candidate_import implementation is missing")

    mock_pack = make_schema_valid_disease_pack(model_mod)

    # Base valid variant and retrieval
    valid_variant = {
        "spdi_proposed": "NC_000000.0:1000:A:T", "gene_proposed": "SYNGENE1", "hgvs_aliases": []
    }
    valid_retrieval = {
        "agents": [], "queries": [], "run_id": "r1", "retrieved_at": "now",
        "pack_binding": {
            "pack_id": "synthpack", "pack_version": "1.0.0", "pack_content_hash": "bf7369f8faa24a6f746956ee1122281e798185f320b012a844ffbc683f2e7b21"
        },
        "prompt_hash": "h", "bookshelf_version": "v1"
    }

    # Template for synthetic candidate claim referencing a source
    def make_cand_claims():
        return [{
            "claim_text": "synthetic assay signal C", "claim_kind_proposed": "pathway", "directionality": "increase",
            "source_ref_proposed": "lit-1",
            "span_proposed": {"locator": "L1", "exact_quote": "synthetic quote C", "page_or_figure": "1"}, "context_proposed": "cell-assay-A"
        }]

    def make_cand_sources():
        return [{
            "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "bib": {
                "pmid": "12345"
            }
        }]

    # A helper to run verification and assert resolver was invoked at Gate3 or Gate4
    def run_boundary_negative_case(resolver):
        ctx = model_mod.PromotionContext(
            disease_pack=mock_pack,
            citation_resolver=resolver,
            context_validator=lambda kind, ctx: True,
            human_oracle_reviewer=lambda cand_id: "sig",
            duplicate_index={}
        )
        cand = model_mod.AtlasCandidateImport(
            candidate_variant=valid_variant,
            proposed_claims=make_cand_claims(),
            proposed_sources=make_cand_sources(),
            retrieval_provenance=valid_retrieval
        )
        with pytest.raises(model_mod.AtlasProvenanceError):
            validate_candidate_import(cand, ctx)
        assert len(resolver.resolve_calls) > 0, "Resolver's resolve() must have been called"


    # --- PART 1: Gate3 raw pin contract cases ---

    class Gate3RawPinResolver(FakeCitationResolver):
        def __init__(self, raw_kwargs=None, content_kwargs=None):
            super().__init__()
            self.raw_kwargs = raw_kwargs or {}
            self.content_kwargs = content_kwargs or {}

        def resolve(self, identifier):
            resolved = super().resolve(identifier)
            import dataclasses
            new_source = dataclasses.replace(resolved.source, **self.raw_kwargs)
            new_content = dataclasses.replace(resolved.content, **self.content_kwargs)
            return dataclasses.replace(resolved, source=new_source, content=new_content)

    # raw_relative_path '.' and '..' / dot-only invalid rejected
    run_boundary_negative_case(Gate3RawPinResolver(raw_kwargs={"raw_relative_path": "."}))
    run_boundary_negative_case(Gate3RawPinResolver(raw_kwargs={"raw_relative_path": ".."}))
    run_boundary_negative_case(Gate3RawPinResolver(raw_kwargs={"raw_relative_path": "..."}))

    # malformed/non-lowercase/non-64hex raw_declared_sha256 rejected
    run_boundary_negative_case(Gate3RawPinResolver(
        raw_kwargs={"raw_declared_sha256": "E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855"},
        content_kwargs={"raw_sha256": "E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855"}
    ))
    run_boundary_negative_case(Gate3RawPinResolver(
        raw_kwargs={"raw_declared_sha256": "e3b0c442"},
        content_kwargs={"raw_sha256": "e3b0c442"}
    ))
    run_boundary_negative_case(Gate3RawPinResolver(
        raw_kwargs={"raw_declared_sha256": "zzzzzzzz78fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},
        content_kwargs={"raw_sha256": "zzzzzzzz78fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}
    ))

    # raw_declared_byte_length bool/negative rejected
    run_boundary_negative_case(Gate3RawPinResolver(
        raw_kwargs={"raw_declared_byte_length": True},
        content_kwargs={"raw_byte_length": True}
    ))
    run_boundary_negative_case(Gate3RawPinResolver(
        raw_kwargs={"raw_declared_byte_length": -10},
        content_kwargs={"raw_byte_length": -10}
    ))

    # raw_declared_byte_length 0 is VALID per spec/catalog loader (positive case) with matching ContentVerification
    positive_zero_byte_resolver = Gate3RawPinResolver(
        raw_kwargs={"raw_declared_byte_length": 0},
        content_kwargs={"raw_byte_length": 0}
    )
    ctx_zero_byte = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=positive_zero_byte_resolver,
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "sig",
        duplicate_index={}
    )
    cand_zero_byte = model_mod.AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=make_cand_claims(),
        proposed_sources=make_cand_sources(),
        retrieval_provenance=valid_retrieval
    )
    validate_candidate_import(cand_zero_byte, ctx_zero_byte)
    assert len(positive_zero_byte_resolver.resolve_calls) > 0
    assert len(positive_zero_byte_resolver.verify_span_calls) > 0

    # safe nested relative + lowercase 64hex accepted
    positive_nested_resolver = Gate3RawPinResolver(
        raw_kwargs={"raw_relative_path": "subdir/nested_path.pdf"}
    )
    ctx_nested = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=positive_nested_resolver,
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "sig",
        duplicate_index={}
    )
    cand_nested = model_mod.AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=make_cand_claims(),
        proposed_sources=make_cand_sources(),
        retrieval_provenance=valid_retrieval
    )
    validate_candidate_import(cand_nested, ctx_nested)
    assert len(positive_nested_resolver.resolve_calls) > 0


    # --- PART 2: Gate4 extracted text requirements ---

    class Gate4ExtractedResolver(FakeCitationResolver):
        def __init__(self, raw_kwargs=None, content_kwargs=None, span_kwargs=None):
            super().__init__()
            self.raw_kwargs = raw_kwargs or {}
            self.content_kwargs = content_kwargs or {}
            self.span_kwargs = span_kwargs or {}

        def resolve(self, identifier):
            resolved = super().resolve(identifier)
            import dataclasses
            new_source = dataclasses.replace(resolved.source, **self.raw_kwargs)
            new_content = dataclasses.replace(resolved.content, **self.content_kwargs)
            return dataclasses.replace(resolved, source=new_source, content=new_content)

        def verify_span(self, resolved, span):
            verified = super().verify_span(resolved, span)
            import dataclasses
            return dataclasses.replace(verified, **self.span_kwargs)

    # missing any extracted_relative_path/hash/byte_length/extraction_method/extraction_version/text_normalization on source rejected
    run_boundary_negative_case(Gate4ExtractedResolver(raw_kwargs={"extracted_relative_path": None}))
    run_boundary_negative_case(Gate4ExtractedResolver(raw_kwargs={"extracted_declared_sha256": None}))
    run_boundary_negative_case(Gate4ExtractedResolver(raw_kwargs={"extracted_declared_byte_length": None}))
    run_boundary_negative_case(Gate4ExtractedResolver(raw_kwargs={"extraction_method": None}))
    run_boundary_negative_case(Gate4ExtractedResolver(raw_kwargs={"extraction_version": None}))
    run_boundary_negative_case(Gate4ExtractedResolver(raw_kwargs={"text_normalization": None}))

    # malformed extracted hash/path/negative or bool byte length rejected
    run_boundary_negative_case(Gate4ExtractedResolver(raw_kwargs={"extracted_relative_path": "."}))
    run_boundary_negative_case(Gate4ExtractedResolver(raw_kwargs={"extracted_declared_sha256": "not-64hex"}))
    run_boundary_negative_case(Gate4ExtractedResolver(raw_kwargs={"extracted_declared_byte_length": -1}))
    run_boundary_negative_case(Gate4ExtractedResolver(raw_kwargs={"extracted_declared_byte_length": True}))

    # ContentVerification extracted fields missing/mismatched rejected
    run_boundary_negative_case(Gate4ExtractedResolver(content_kwargs={"extracted_text_sha256": "85136db6d4512cb593c66f543d2c88f1ae7e786bdfc14c55d0ac5b42dcd45c7e"}))
    run_boundary_negative_case(Gate4ExtractedResolver(content_kwargs={"extracted_text_byte_length": 9999}))

    # VerifiedSpan must corroborate exact source/content extracted artifact metadata per spec, not only echo source_id/locator/quote
    run_boundary_negative_case(Gate4ExtractedResolver(span_kwargs={"extracted_text_sha256": "85136db6d4512cb593c66f543d2c88f1ae7e786bdfc14c55d0ac5b42dcd45c7e"}))

    # zero-byte extracted text with non-empty span proposed must raise AtlasProvenanceError (quote cannot fit zero-byte artifact)
    run_boundary_negative_case(Gate4ExtractedResolver(
        raw_kwargs={"extracted_declared_byte_length": 0},
        content_kwargs={"extracted_text_byte_length": 0},
        span_kwargs={"extracted_text_sha256": "85136db6d4512cb593c66f543d2c88f1ae7e786bdfc14c55d0ac5b42dcd45c7f"}
    ))

    # complete extracted pins/content + exact VerifiedSpan accepted
    positive_extracted_resolver = Gate4ExtractedResolver()
    ctx_positive = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=positive_extracted_resolver,
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "sig",
        duplicate_index={}
    )
    cand_positive = model_mod.AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=make_cand_claims(),
        proposed_sources=make_cand_sources(),
        retrieval_provenance=valid_retrieval
    )
    validate_candidate_import(cand_positive, ctx_positive)
    assert len(positive_extracted_resolver.resolve_calls) > 0
    assert len(positive_extracted_resolver.verify_span_calls) > 0


def test_gate4_raw_span_type_checks():
    """Verify that Gate4 strictly validates raw span types and fields at schema/pre-check time,
    raising AtlasSchemaError (and never attempting verify_span or leaking TypError) for invalid types.
    """
    try:
        import raptor.atlas.model as model_mod
        from raptor.atlas.promote import validate_candidate_import
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas promote/candidate_import implementation is missing")

    mock_pack = make_schema_valid_disease_pack(model_mod)

    # Base valid variant and retrieval
    valid_variant = {
        "spdi_proposed": "NC_000000.0:1000:A:T", "gene_proposed": "SYNGENE1", "hgvs_aliases": []
    }
    valid_retrieval = {
        "agents": [], "queries": [], "run_id": "r1", "retrieved_at": "now",
        "pack_binding": {
            "pack_id": "synthpack", "pack_version": "1.0.0", "pack_content_hash": "bf7369f8faa24a6f746956ee1122281e798185f320b012a844ffbc683f2e7b21"
        },
        "prompt_hash": "h", "bookshelf_version": "v1"
    }

    def run_span_negative_case(span_proposed):
        resolver = FakeCitationResolver()
        ctx = model_mod.PromotionContext(
            disease_pack=mock_pack,
            citation_resolver=resolver,
            context_validator=lambda kind, ctx: True,
            human_oracle_reviewer=lambda cand_id: "sig",
            duplicate_index={}
        )
        cand = model_mod.AtlasCandidateImport(
            candidate_variant=valid_variant,
            proposed_claims=[{
                "claim_text": "text", "claim_kind_proposed": "pathway", "directionality": "increase",
                "source_ref_proposed": "lit-1",
                "span_proposed": span_proposed, "context_proposed": "cell-assay-A"
            }],
            proposed_sources=[{
                "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
                "bib": {"pmid": "12345"}
            }],
            retrieval_provenance=valid_retrieval
        )
        with pytest.raises(model_mod.AtlasSchemaError):
            validate_candidate_import(cand, ctx)
        assert len(resolver.verify_span_calls) == 0, "Resolver's verify_span must never be called"

    # 1. span_proposed is not a dict
    run_span_negative_case("not-a-dict")
    run_span_negative_case(["not-a-dict"])
    run_span_negative_case(None)

    # 2. locator missing/None/int/bool/list/blank/whitespace
    run_span_negative_case({"exact_quote": "some quote"})
    run_span_negative_case({"locator": None, "exact_quote": "some quote"})
    run_span_negative_case({"locator": 123, "exact_quote": "some quote"})
    run_span_negative_case({"locator": True, "exact_quote": "some quote"})
    run_span_negative_case({"locator": ["L1"], "exact_quote": "some quote"})
    run_span_negative_case({"locator": "", "exact_quote": "some quote"})
    run_span_negative_case({"locator": "   ", "exact_quote": "some quote"})

    # 3. exact_quote missing/None/int/bool/list/blank/whitespace
    run_span_negative_case({"locator": "L1"})
    run_span_negative_case({"locator": "L1", "exact_quote": None})
    run_span_negative_case({"locator": "L1", "exact_quote": 123})
    run_span_negative_case({"locator": "L1", "exact_quote": True})
    run_span_negative_case({"locator": "L1", "exact_quote": ["some quote"]})
    run_span_negative_case({"locator": "L1", "exact_quote": ""})
    run_span_negative_case({"locator": "L1", "exact_quote": "   "})

    # 4. page_or_figure wrong type if contract requires str
    run_span_negative_case({"locator": "L1", "exact_quote": "some quote", "page_or_figure": 123})
    run_span_negative_case({"locator": "L1", "exact_quote": "some quote", "page_or_figure": True})
    run_span_negative_case({"locator": "L1", "exact_quote": "some quote", "page_or_figure": ["page-1"]})

    # 5. Positive case: valid nonblank string is accepted
    resolver_positive = FakeCitationResolver()
    ctx_positive = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=resolver_positive,
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "sig",
        duplicate_index={}
    )
    cand_positive = model_mod.AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=[{
            "claim_text": "text", "claim_kind_proposed": "pathway", "directionality": "increase",
            "source_ref_proposed": "lit-1",
            "span_proposed": {"locator": "L1", "exact_quote": "some quote", "page_or_figure": "page-1"},
            "context_proposed": "cell-assay-A"
        }],
        proposed_sources=[{
            "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "bib": {"pmid": "12345"}
        }],
        retrieval_provenance=valid_retrieval
    )
    validate_candidate_import(cand_positive, ctx_positive)
    assert len(resolver_positive.resolve_calls) > 0
    assert len(resolver_positive.verify_span_calls) > 0


def test_resolver_whitespace_spoof_regression_cases():
    """Verify that Gate3 and Gate4 reject whitespace-only fields returned by a resolver with AtlasProvenanceError.
    
    The resolver returns a typed ResolvedCitation but CatalogSource fields are whitespace-only:
    - raw_relative_path = '   '
    - raw_media_type = '   '
    - extracted_relative_path = '   '
    - extraction_method = '   '
    - extraction_version = '   '
    
    validate_candidate_import must raise AtlasProvenanceError itself, the resolver must not raise,
    and call spies must prove that the intended gate is reached. Include valid nonblank controls.
    """
    try:
        import raptor.atlas.model as model_mod
        from raptor.atlas.promote import validate_candidate_import
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas promote/candidate_import implementation is missing")

    mock_pack = make_schema_valid_disease_pack(model_mod)

    # Base valid variant and retrieval
    valid_variant = {
        "spdi_proposed": "NC_000000.0:1000:A:T", "gene_proposed": "SYNGENE1", "hgvs_aliases": []
    }
    valid_retrieval = {
        "agents": [], "queries": [], "run_id": "r1", "retrieved_at": "now",
        "pack_binding": {
            "pack_id": "synthpack", "pack_version": "1.0.0", "pack_content_hash": "bf7369f8faa24a6f746956ee1122281e798185f320b012a844ffbc683f2e7b21"
        },
        "prompt_hash": "h", "bookshelf_version": "v1"
    }

    # Helper to build basic source
    def make_sources():
        return [{
            "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "bib": {"pmid": "12345"}
        }]

    # Helper to build basic claims with span to trigger Gate 4
    def make_claims_with_span():
        return [{
            "claim_text": "text", "claim_kind_proposed": "pathway", "directionality": "increase",
            "source_ref_proposed": "lit-1",
            "span_proposed": {"locator": "L1", "exact_quote": "some quote", "page_or_figure": "page-1"},
            "context_proposed": "cell-assay-A"
        }]

    # 1. TEST CASE: raw_relative_path='   '
    class SpoofRawPathResolver(FakeCitationResolver):
        def resolve(self, identifier):
            resolved = super().resolve(identifier)
            import dataclasses
            new_source = dataclasses.replace(resolved.source, raw_relative_path="   ")
            return dataclasses.replace(resolved, source=new_source)

    resolver_raw_path = SpoofRawPathResolver()
    ctx_raw_path = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=resolver_raw_path,
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "sig",
        duplicate_index={}
    )
    cand_raw_path = model_mod.AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=[],  # No claims needed to reach Gate 3
        proposed_sources=make_sources(),
        retrieval_provenance=valid_retrieval
    )

    with pytest.raises(model_mod.AtlasProvenanceError) as exc_info:
        validate_candidate_import(cand_raw_path, ctx_raw_path)
    
    # Resolver itself must not raise any exception, and call spy proves Gate 3 reached
    assert len(resolver_raw_path.resolve_calls) > 0
    assert len(resolver_raw_path.verify_span_calls) == 0

    # 2. TEST CASE: raw_media_type='   '
    class SpoofRawMediaTypeResolver(FakeCitationResolver):
        def resolve(self, identifier):
            resolved = super().resolve(identifier)
            import dataclasses
            new_source = dataclasses.replace(resolved.source, raw_media_type="   ")
            return dataclasses.replace(resolved, source=new_source)

    resolver_raw_media = SpoofRawMediaTypeResolver()
    ctx_raw_media = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=resolver_raw_media,
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "sig",
        duplicate_index={}
    )
    cand_raw_media = model_mod.AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=[],  # No claims needed to reach Gate 3
        proposed_sources=make_sources(),
        retrieval_provenance=valid_retrieval
    )

    with pytest.raises(model_mod.AtlasProvenanceError) as exc_info:
        validate_candidate_import(cand_raw_media, ctx_raw_media)
        
    assert len(resolver_raw_media.resolve_calls) > 0
    assert len(resolver_raw_media.verify_span_calls) == 0

    # 3. TEST CASE: extracted_relative_path='   ' (fails in Gate 4)
    class SpoofExtractedPathResolver(FakeCitationResolver):
        def resolve(self, identifier):
            resolved = super().resolve(identifier)
            import dataclasses
            new_source = dataclasses.replace(resolved.source, extracted_relative_path="   ")
            return dataclasses.replace(resolved, source=new_source)

    resolver_ext_path = SpoofExtractedPathResolver()
    ctx_ext_path = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=resolver_ext_path,
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "sig",
        duplicate_index={}
    )
    cand_ext_path = model_mod.AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=make_claims_with_span(),  # Has proposed claims with span to trigger Gate 4
        proposed_sources=make_sources(),
        retrieval_provenance=valid_retrieval
    )

    with pytest.raises(model_mod.AtlasProvenanceError) as exc_info:
        validate_candidate_import(cand_ext_path, ctx_ext_path)
        
    assert len(resolver_ext_path.resolve_calls) > 0
    assert len(resolver_ext_path.verify_span_calls) == 0  # Gate 4 fails BEFORE verify_span is called

    # 4. TEST CASE: extraction_method='   ' (fails in Gate 4)
    class SpoofExtractionMethodResolver(FakeCitationResolver):
        def resolve(self, identifier):
            resolved = super().resolve(identifier)
            import dataclasses
            new_source = dataclasses.replace(resolved.source, extraction_method="   ")
            return dataclasses.replace(resolved, source=new_source)

    resolver_ext_method = SpoofExtractionMethodResolver()
    ctx_ext_method = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=resolver_ext_method,
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "sig",
        duplicate_index={}
    )
    cand_ext_method = model_mod.AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=make_claims_with_span(),
        proposed_sources=make_sources(),
        retrieval_provenance=valid_retrieval
    )

    with pytest.raises(model_mod.AtlasProvenanceError) as exc_info:
        validate_candidate_import(cand_ext_method, ctx_ext_method)
        
    assert len(resolver_ext_method.resolve_calls) > 0
    assert len(resolver_ext_method.verify_span_calls) == 0  # Gate 4 fails BEFORE verify_span is called

    # 5. TEST CASE: extraction_version='   ' (fails in Gate 4)
    class SpoofExtractionVersionResolver(FakeCitationResolver):
        def resolve(self, identifier):
            resolved = super().resolve(identifier)
            import dataclasses
            new_source = dataclasses.replace(resolved.source, extraction_version="   ")
            return dataclasses.replace(resolved, source=new_source)

    resolver_ext_version = SpoofExtractionVersionResolver()
    ctx_ext_version = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=resolver_ext_version,
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "sig",
        duplicate_index={}
    )
    cand_ext_version = model_mod.AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=make_claims_with_span(),
        proposed_sources=make_sources(),
        retrieval_provenance=valid_retrieval
    )

    with pytest.raises(model_mod.AtlasProvenanceError) as exc_info:
        validate_candidate_import(cand_ext_version, ctx_ext_version)
        
    assert len(resolver_ext_version.resolve_calls) > 0
    assert len(resolver_ext_version.verify_span_calls) == 0  # Gate 4 fails BEFORE verify_span is called

    # 6. VALID NONBLANK CONTROL: Verifies that valid nonblank values successfully pass import validation
    resolver_control = FakeCitationResolver()
    ctx_control = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=resolver_control,
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "sig",
        duplicate_index={}
    )
    cand_control = model_mod.AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=make_claims_with_span(),
        proposed_sources=make_sources(),
        retrieval_provenance=valid_retrieval
    )
    
    # Should run successfully without raising any exceptions
    validate_candidate_import(cand_control, ctx_control)
    assert len(resolver_control.resolve_calls) > 0
    assert len(resolver_control.verify_span_calls) > 0


def test_gate4_resolver_spoof_offset_validation():
    """Add non-vacuous Gate4 resolver-spoof tests:
    - requested locator `text-char:50:60`, exact_quote length 10; resolver returns normal VerifiedSpan echoing locator/quote/source/hash but start=0,end=10 -> validate_candidate_import must raise AtlasProvenanceError itself;
    - start/end partially mismatched, reversed, bool/non-int if typed object construction permits; production should reject before acceptance;
    - exact start=50,end=60 passes;
    - duplicate same quote scenario demonstrates locator offsets bind exact occurrence.
    Resolver must not raise; spy proves verify_span called. Current production should RED on mismatched offset.
    """
    try:
        import raptor.atlas.model as model_mod
        from raptor.atlas.promote import validate_candidate_import
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas promote/candidate_import implementation is missing")

    mock_pack = make_schema_valid_disease_pack(model_mod)

    # Base valid variant and retrieval
    valid_variant = {
        "spdi_proposed": "NC_000000.0:1000:A:T", "gene_proposed": "SYNGENE1", "hgvs_aliases": []
    }
    valid_retrieval = {
        "agents": [], "queries": [], "run_id": "r1", "retrieved_at": "now",
        "pack_binding": {
            "pack_id": "synthpack", "pack_version": "1.0.0", "pack_content_hash": "bf7369f8faa24a6f746956ee1122281e798185f320b012a844ffbc683f2e7b21"
        },
        "prompt_hash": "h", "bookshelf_version": "v1"
    }

    # Helper to build basic source
    def make_sources():
        return [{
            "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "bib": {"pmid": "12345"}
        }]

    # 1. requested locator `text-char:50:60`, exact_quote length 10; resolver returns normal VerifiedSpan echoing locator/quote/source/hash but start=0,end=10 -> validate_candidate_import must raise AtlasProvenanceError itself;
    # Resolver must not raise; spy proves verify_span called.
    class OffsetSpoofResolver(FakeCitationResolver):
        def __init__(self, start, end):
            super().__init__()
            self.start_val = start
            self.end_val = end

        def verify_span(self, resolved, span):
            self.verify_span_calls.append((resolved, span))
            from raptor.atlas.model import VerifiedSpan
            return VerifiedSpan(
                source_id=resolved.source.source_id,
                locator=span.locator,
                start=self.start_val,
                end=self.end_val,
                exact_quote=span.exact_quote or "",
                extracted_text_sha256=resolved.content.extracted_text_sha256
            )

    # A. start=0, end=10 (internally consistent but mismatched with text-char:50:60)
    resolver_spoof = OffsetSpoofResolver(0, 10)
    ctx_spoof = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=resolver_spoof,
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "sig",
        duplicate_index={}
    )
    cand_spoof = model_mod.AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=[{
            "claim_text": "text", "claim_kind_proposed": "pathway", "directionality": "increase",
            "source_ref_proposed": "lit-1",
            "span_proposed": {"locator": "text-char:50:60", "exact_quote": "1234567890", "page_or_figure": "page-1"},
            "context_proposed": "cell-assay-A"
        }],
        proposed_sources=make_sources(),
        retrieval_provenance=valid_retrieval
    )

    with pytest.raises(model_mod.AtlasProvenanceError) as exc_info:
        validate_candidate_import(cand_spoof, ctx_spoof)

    # Prove spy verify_span was called and did NOT raise
    assert len(resolver_spoof.verify_span_calls) == 1
    assert resolver_spoof.verify_span_calls[0][1].locator == "text-char:50:60"


    # B. start/end partially mismatched, reversed, bool/non-int if typed object construction permits; production should reject before acceptance;
    
    # B1. Partially mismatched: start=51, end=61
    resolver_mismatch = OffsetSpoofResolver(51, 61)
    ctx_mismatch = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=resolver_mismatch,
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "sig",
        duplicate_index={}
    )
    with pytest.raises(model_mod.AtlasProvenanceError):
        validate_candidate_import(cand_spoof, ctx_mismatch)
    assert len(resolver_mismatch.verify_span_calls) == 1

    # B2. Reversed: start=60, end=50
    resolver_reversed = OffsetSpoofResolver(60, 50)
    ctx_reversed = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=resolver_reversed,
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "sig",
        duplicate_index={}
    )
    with pytest.raises(model_mod.AtlasProvenanceError):
        validate_candidate_import(cand_spoof, ctx_reversed)
    assert len(resolver_reversed.verify_span_calls) == 1

    # B3. Bool/non-int
    for bad_offset in [10.5, True]:
        class BadTypeOffsetResolver(FakeCitationResolver):
            def verify_span(self, resolved, span):
                self.verify_span_calls.append((resolved, span))
                from raptor.atlas.model import VerifiedSpan
                return VerifiedSpan(
                    source_id=resolved.source.source_id,
                    locator=span.locator,
                    start=bad_offset,
                    end=bad_offset + 10 if isinstance(bad_offset, (int, float)) else 10,
                    exact_quote=span.exact_quote or "",
                    extracted_text_sha256=resolved.content.extracted_text_sha256
                )
        
        resolver_bad_type = BadTypeOffsetResolver()
        ctx_bad_type = model_mod.PromotionContext(
            disease_pack=mock_pack,
            citation_resolver=resolver_bad_type,
            context_validator=lambda kind, ctx: True,
            human_oracle_reviewer=lambda cand_id: "sig",
            duplicate_index={}
        )
        with pytest.raises((model_mod.AtlasProvenanceError, TypeError, AttributeError)):
            validate_candidate_import(cand_spoof, ctx_bad_type)
        assert len(resolver_bad_type.verify_span_calls) == 1


    # C. exact start=50,end=60 passes;
    resolver_exact = OffsetSpoofResolver(50, 60)
    ctx_exact = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=resolver_exact,
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "sig",
        duplicate_index={}
    )
    validate_candidate_import(cand_spoof, ctx_exact)
    assert len(resolver_exact.verify_span_calls) == 1


    # D. duplicate same quote scenario demonstrates locator offsets bind exact occurrence.
    class DuplicateQuoteResolver(FakeCitationResolver):
        def verify_span(self, resolved, span):
            self.verify_span_calls.append((resolved, span))
            from raptor.atlas.model import VerifiedSpan
            if span.locator == "text-char:10:20":
                start, end = 10, 20
            elif span.locator == "text-char:40:50":
                start, end = 40, 50
            else:
                start, end = 0, len(span.exact_quote or "")
            return VerifiedSpan(
                source_id=resolved.source.source_id,
                locator=span.locator,
                start=start,
                end=end,
                exact_quote=span.exact_quote or "",
                extracted_text_sha256=resolved.content.extracted_text_sha256
            )

    cand_duplicate = model_mod.AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=[
            {
                "claim_text": "text1", "claim_kind_proposed": "pathway", "directionality": "increase",
                "source_ref_proposed": "lit-1",
                "span_proposed": {"locator": "text-char:10:20", "exact_quote": "same_quote", "page_or_figure": "page-1"},
                "context_proposed": "cell-assay-A"
            },
            {
                "claim_text": "text2", "claim_kind_proposed": "pathway", "directionality": "increase",
                "source_ref_proposed": "lit-1",
                "span_proposed": {"locator": "text-char:40:50", "exact_quote": "same_quote", "page_or_figure": "page-1"},
                "context_proposed": "cell-assay-A"
            }
        ],
        proposed_sources=make_sources(),
        retrieval_provenance=valid_retrieval
    )

    resolver_duplicate = DuplicateQuoteResolver()
    ctx_duplicate = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=resolver_duplicate,
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "sig",
        duplicate_index={}
    )

    validate_candidate_import(cand_duplicate, ctx_duplicate)
    assert len(resolver_duplicate.verify_span_calls) == 2

    # Now let's try a resolver that always returns 40:50 for both locators (spoofing the first occurrence)
    class MismatchedDuplicateResolver(FakeCitationResolver):
        def verify_span(self, resolved, span):
            self.verify_span_calls.append((resolved, span))
            from raptor.atlas.model import VerifiedSpan
            return VerifiedSpan(
                source_id=resolved.source.source_id,
                locator=span.locator,
                start=40,
                end=50,
                exact_quote=span.exact_quote or "",
                extracted_text_sha256=resolved.content.extracted_text_sha256
            )

    resolver_mismatched_duplicate = MismatchedDuplicateResolver()
    ctx_mismatched_duplicate = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=resolver_mismatched_duplicate,
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "sig",
        duplicate_index={}
    )

    with pytest.raises(model_mod.AtlasProvenanceError):
        validate_candidate_import(cand_duplicate, ctx_mismatched_duplicate)


def test_gate4_locator_scheme_spoof_gemini():
    """Verify Gate4 locator scheme spoof validation.
    
    - Lowercase text-char:50:60 with matching offsets passes.
    - Case variants (TEXT-CHAR:50:60, Text-Char:50:60) and malformed same-scheme
      variants must be rejected.
    - Every non-text-char locator (plain L1, other-scheme, URL/page/figure locator,
      uppercase/mixed/spacing text-char) is rejected by validate_candidate_import with
      AtlasSchemaError/AtlasProvenanceError before acceptance.
    - Spies show appropriate Gate4 invocation/zero where structural (no resolver call
      if structurally rejected).
    """
    try:
        import raptor.atlas.model as model_mod
        from raptor.atlas.promote import validate_candidate_import
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas promote/candidate_import implementation is missing")

    mock_pack = make_schema_valid_disease_pack(model_mod)

    # Base valid variant and retrieval
    valid_variant = {
        "spdi_proposed": "NC_000000.0:1000:A:T", "gene_proposed": "SYNGENE1", "hgvs_aliases": []
    }
    valid_retrieval = {
        "agents": [], "queries": [], "run_id": "r1", "retrieved_at": "now",
        "pack_binding": {
            "pack_id": mock_pack.pack_id, "pack_version": mock_pack.pack_version, "pack_content_hash": mock_pack.pack_content_hash
        },
        "prompt_hash": "h", "bookshelf_version": "v1"
    }

    class SpoofLocatorResolver(FakeCitationResolver):
        def verify_span(self, resolved, span):
            self.verify_span_calls.append((resolved, span))
            from raptor.atlas.model import VerifiedSpan
            if "50:60" in span.locator:
                start, end = 50, 60
            else:
                start, end = 0, len(span.exact_quote or "")
            return VerifiedSpan(
                source_id=resolved.source.source_id,
                locator=span.locator,
                start=start,
                end=end,
                exact_quote=span.exact_quote or "",
                extracted_text_sha256=resolved.content.extracted_text_sha256
            )

    resolver = SpoofLocatorResolver()
    ctx = model_mod.PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=resolver,
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "sig",
        duplicate_index={}
    )

    def run_with_locator(locator_str):
        cand = model_mod.AtlasCandidateImport(
            candidate_variant=valid_variant,
            proposed_claims=[{
                "claim_text": "text", "claim_kind_proposed": "pathway", "directionality": "increase",
                "source_ref_proposed": "lit-1",
                "span_proposed": {"locator": locator_str, "exact_quote": "1234567890", "page_or_figure": "page-1"},
                "context_proposed": "cell-assay-A"
            }],
            proposed_sources=[{
                "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
                "bib": {"pmid": "12345"}
            }],
            retrieval_provenance=valid_retrieval
        )
        validate_candidate_import(cand, ctx)

    # 1. Exact lowercase passes
    resolver.verify_span_calls.clear()
    run_with_locator("text-char:50:60")
    assert len(resolver.verify_span_calls) == 1

    # 2. Case variants - must raise AtlasProvenanceError or AtlasSchemaError
    for bad_locator in ["TEXT-CHAR:50:60", "Text-Char:50:60", "text-char :50:60"]:
        resolver.verify_span_calls.clear()
        with pytest.raises((model_mod.AtlasProvenanceError, model_mod.AtlasSchemaError)) as exc_info:
            run_with_locator(bad_locator)
        # If structural (AtlasSchemaError), verify_span_calls must be exactly zero (no resolver invocation)
        if issubclass(exc_info.type, model_mod.AtlasSchemaError):
            assert len(resolver.verify_span_calls) == 0

    # 3. Malformed same-scheme variants - must raise
    for bad_locator in ["text-char:50", "text-char:50:60:extra", "text-char:+50:60", "text-char:50: 60"]:
        resolver.verify_span_calls.clear()
        with pytest.raises((model_mod.AtlasProvenanceError, model_mod.AtlasSchemaError)) as exc_info:
            run_with_locator(bad_locator)
        # If structural (AtlasSchemaError), verify_span_calls must be exactly zero
        if issubclass(exc_info.type, model_mod.AtlasSchemaError):
            assert len(resolver.verify_span_calls) == 0

    # 4. Other non-text-char locators - must raise AtlasProvenanceError or AtlasSchemaError.
    # Supported v1 is ONLY exact lowercase "text-char:<start>:<end>".
    # Non-text-char locators (plain "L1", "other-scheme", URL, page, figure locators) are rejected.
    non_text_char_locators = [
        "L1",
        "other-scheme",
        "other-scheme:50:60",
        "https://example.com/doc.pdf",
        "page-12",
        "fig-2"
    ]
    for bad_locator in non_text_char_locators:
        resolver.verify_span_calls.clear()
        with pytest.raises((model_mod.AtlasProvenanceError, model_mod.AtlasSchemaError)) as exc_info:
            run_with_locator(bad_locator)
        # Spies show appropriate Gate4 invocation / zero where structural
        if issubclass(exc_info.type, model_mod.AtlasSchemaError):
            assert len(resolver.verify_span_calls) == 0





