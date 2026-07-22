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


def test_candidate_import_exact_schema():
    """Verify that AtlasCandidateImport matches the exact spec schema with nested fields and no top-level flat fields."""
    try:
        from raptor.atlas.model import AtlasCandidateImport, AtlasSchemaError
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas promote/candidate_import implementation is missing")

    # Base valid structures
    candidate_variant = {
        "spdi_proposed": "NC_000000.0:1000:A:T",
        "gene_proposed": "SYNGENE1",
        "hgvs_aliases": ("g.1000A>T",)
    }
    retrieval_provenance = {
        "agents": ("agent-1",),
        "queries": ("query-1",),
        "run_id": "run-001",
        "retrieved_at": "2026-07-23T01:00:00Z",
        "pack_binding": {
            "pack_id": "synthpack",
            "pack_version": "1.0.0",
            "pack_content_hash": "mock_hash"
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
        proposed_claims=(),
        proposed_sources=(),
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
            proposed_claims=(),
            proposed_sources=(),
            retrieval_provenance=retrieval_provenance,
            status="proposed"  # Flat top-level field is WRONG
        )


def test_promotion_context_fields():
    """Verify PromotionContext fields strictly conform to the spec."""
    try:
        from raptor.atlas.model import PromotionContext
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas promote/candidate_import implementation is missing")

    fields_list = [f.name for f in dataclasses.fields(PromotionContext)]
    expected = ["disease_pack", "citation_resolver", "context_validator", "human_oracle_reviewer", "duplicate_index"]
    for field in expected:
        assert field in fields_list, f"PromotionContext is missing expected field: {field}"


def test_eight_gates_ordered_execution_and_short_circuiting():
    """Verify that validate_candidate_import executes the 8 gates in strict order, instrumenting short-circuiting on failure."""
    try:
        from raptor.atlas.model import (
            AtlasCandidateImport, PromotionContext, DiseasePack, PackBinding,
            AtlasSchemaError, AtlasIdentityError, AtlasProvenanceError, AtlasLeakageError
        )
        from raptor.atlas.promote import validate_candidate_import
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas promote/candidate_import implementation is missing")

    # 1. Mock disease pack
    mock_pack = DiseasePack(
        schema="atlas.disease_pack.v1",
        pack_id="synthpack",
        pack_version="1.0.0",
        pack_content_hash="mock_hash",
        allowed_genes=("SYNGENE1",),
        assembly_pins=("GRCh38",),
        transcript_pins=(),
        reconciliation_policy={},
        ontology_extensions={
            "allowed_kinds": ("pathway", "localization"),
            "allowed_contexts": ("cell-assay-A",)
        },
        source_register_pins=(),
        prohibitions={},
        pilot_eval_metadata={}
    )

    # 2. Instrumentation: we create wrappers for the DI callables to trace calls
    calls = []

    def citation_resolver(pmid_or_doi):
        calls.append("citation_resolver")
        # Fail on "fail-citation"
        if pmid_or_doi == "fail-citation":
            return False
        return True

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

    # Base valid pieces
    valid_variant = {
        "spdi_proposed": "NC_000000.0:1000:A:T",
        "gene_proposed": "SYNGENE1",
        "hgvs_aliases": ()
    }
    # retrieval_provenance.pack_binding must be a real matching binding copy
    valid_retrieval = {
        "agents": (), "queries": (), "run_id": "r1", "retrieved_at": "now",
        "pack_binding": {
            "pack_id": "synthpack",
            "pack_version": "1.0.0",
            "pack_content_hash": "mock_hash"
        },
        "prompt_hash": "h", "bookshelf_version": "v1"
    }

    # Gate 1 failed (canonical_spdi_readmission) -> should raise AtlasIdentityError and not call anything else
    cand_g1_fail = AtlasCandidateImport(
        candidate_variant={
            "spdi_proposed": "NC_000000.0:1000:A:T",
            "gene_proposed": "OFF_PACK_GENE",  # G1 check: off-pack gene raises
            "hgvs_aliases": ()
        },
        proposed_claims=(),
        proposed_sources=(),
        retrieval_provenance=valid_retrieval
    )

    ctx = PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=citation_resolver,
        context_validator=context_validator,
        human_oracle_reviewer=human_oracle_reviewer,
        duplicate_index={}
    )

    calls.clear()
    with pytest.raises((AtlasIdentityError, AtlasSchemaError)):
        validate_candidate_import(cand_g1_fail, ctx)
    assert len(calls) == 0, "No collaborators should be invoked when Gate 1 (identity) fails"

    # Gate 2 failed (source_type_role_validation)
    # Role is direct_evidence_leaf, but source_type is primary_lit_wrong (not PRIMARY-LIT or DATASET)
    cand_g2_fail = AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=(),
        proposed_sources=({
            "entry_id": "lit-1", "source_type": "PRIMARY-OFFICIAL", "role": "direct_evidence_leaf",
            "bib": {"pmid": "12345"}
        },),
        retrieval_provenance=valid_retrieval
    )
    calls.clear()
    with pytest.raises(AtlasSchemaError):
        validate_candidate_import(cand_g2_fail, ctx)
    assert len(calls) == 0, "No collaborators should be invoked when Gate 2 (source-role/type) fails"

    # Gate 3 failed (citation_resolution) -> citation_resolver is invoked and fails; no subsequent gates called
    cand_g3_fail = AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=(),
        proposed_sources=({
            "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "bib": {"pmid": "fail-citation"}
        },),
        retrieval_provenance=valid_retrieval
    )
    calls.clear()
    with pytest.raises(AtlasProvenanceError):
        validate_candidate_import(cand_g3_fail, ctx)
    assert "citation_resolver" in calls
    assert "context_validator" not in calls
    assert "human_oracle_reviewer" not in calls

    # Gate 4 failed (exact_span_resolution) -> claim missing span
    cand_g4_fail = AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=({
            "claim_text": "text", "claim_kind_proposed": "pathway", "directionality": "increase",
            "source_ref_proposed": "lit-1", "span_proposed": None, "context_proposed": "cell-assay-A"
        },),
        proposed_sources=({
            "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "bib": {"pmid": "resolved-pmid"}
        },),
        retrieval_provenance=valid_retrieval
    )
    calls.clear()
    with pytest.raises(AtlasSchemaError):
        validate_candidate_import(cand_g4_fail, ctx)
    # Since citation resolution is Gate 3, it should be called before Gate 4 checks span!
    assert "citation_resolver" in calls
    assert "context_validator" not in calls
    assert "human_oracle_reviewer" not in calls

    # Gate 5 failed (context_ontology_pack_validation) -> context_validator is invoked and fails
    cand_g5_fail = AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=({
            "claim_text": "text", "claim_kind_proposed": "fail-kind", "directionality": "increase",
            "source_ref_proposed": "lit-1",
            "span_proposed": {"locator": "L1", "exact_quote": "Q1", "page_or_figure": "1"}, "context_proposed": "cell-assay-A"
        },),
        proposed_sources=({
            "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "bib": {"pmid": "resolved-pmid"}
        },),
        retrieval_provenance=valid_retrieval
    )
    calls.clear()
    with pytest.raises(AtlasSchemaError):
        validate_candidate_import(cand_g5_fail, ctx)
    assert "citation_resolver" in calls
    assert "context_validator" in calls
    assert "human_oracle_reviewer" not in calls

    # Gate 6 failed (duplicate_conflict_rules) -> fails on conflict register
    duplicate_conflict_index = {
        "c1": "conflict"  # register conflict for claim c1
    }
    cand_g6_fail = AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=({
            "claim_text": "text", "claim_kind_proposed": "pathway", "directionality": "increase",
            "source_ref_proposed": "lit-1",
            "span_proposed": {"locator": "L1", "exact_quote": "Q1", "page_or_figure": "1"}, "context_proposed": "cell-assay-A"
        },),
        proposed_sources=({
            "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "bib": {"pmid": "resolved-pmid"}
        },),
        retrieval_provenance=valid_retrieval
    )
    ctx_conflict = PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=citation_resolver,
        context_validator=context_validator,
        human_oracle_reviewer=human_oracle_reviewer,
        duplicate_index=duplicate_conflict_index
    )
    calls.clear()
    with pytest.raises(AtlasProvenanceError):
        validate_candidate_import(cand_g6_fail, ctx_conflict)
    assert "citation_resolver" in calls
    assert "context_validator" in calls
    assert "human_oracle_reviewer" not in calls

    # Gate 7 failed (no_classification_leakage) -> raises AtlasLeakageError / AtlasProvenanceError
    cand_g7_fail = AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=({
            "claim_text": "text", "claim_kind_proposed": "pathway", "directionality": "increase",
            "source_ref_proposed": "lit-1",
            "span_proposed": {"locator": "L1", "exact_quote": "Q1", "page_or_figure": "1"}, "context_proposed": "cell-assay-A",
            "classifier_score": 0.95  # LEAKAGE!
        },),
        proposed_sources=({
            "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "bib": {"pmid": "resolved-pmid"}
        },),
        retrieval_provenance=valid_retrieval
    )
    calls.clear()
    with pytest.raises((AtlasLeakageError, AtlasProvenanceError)):
        validate_candidate_import(cand_g7_fail, ctx)
    assert "citation_resolver" in calls
    assert "context_validator" in calls
    assert "human_oracle_reviewer" not in calls

    # Gate 8 failed (named_human_oracle_span_review) -> oracle returns None
    cand_g8_fail = AtlasCandidateImport(
        candidate_variant=valid_variant,
        proposed_claims=({
            "claim_text": "text", "claim_kind_proposed": "pathway", "directionality": "increase",
            "source_ref_proposed": "fail-human",
            "span_proposed": {"locator": "L1", "exact_quote": "Q1", "page_or_figure": "1"}, "context_proposed": "cell-assay-A"
        },),
        proposed_sources=({
            "entry_id": "fail-human", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "bib": {"pmid": "resolved-pmid"}
        },),
        retrieval_provenance=valid_retrieval
    )
    calls.clear()
    with pytest.raises(AtlasProvenanceError):
        validate_candidate_import(cand_g8_fail, ctx)
    assert "citation_resolver" in calls
    assert "context_validator" in calls
    assert "human_oracle_reviewer" in calls


def test_wrong_pack_mismatch_negative():
    """Verify that a mismatch between retrieval_provenance.pack_binding and context's disease pack raises AtlasSchemaError."""
    try:
        from raptor.atlas.model import (
            AtlasCandidateImport, PromotionContext, DiseasePack, PackBinding, AtlasSchemaError
        )
        from raptor.atlas.promote import validate_candidate_import
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas promote/candidate_import implementation is missing")

    mock_pack = DiseasePack(
        schema="atlas.disease_pack.v1",
        pack_id="synthpack", pack_version="1.0.0", pack_content_hash="mock_hash",
        allowed_genes=("SYNGENE1",), assembly_pins=("GRCh38",), transcript_pins=(),
        reconciliation_policy={}, ontology_extensions={}, source_register_pins=(),
        prohibitions={}, pilot_eval_metadata={}
    )

    # Retrieval pack_version mismatches (1.0.1 instead of 1.0.0)
    invalid_retrieval_pack = {
        "agents": (), "queries": (), "run_id": "r1", "retrieved_at": "now",
        "pack_binding": {
            "pack_id": "synthpack",
            "pack_version": "1.0.1",
            "pack_content_hash": "mock_hash"
        },
        "prompt_hash": "h", "bookshelf_version": "v1"
    }

    cand = AtlasCandidateImport(
        candidate_variant={
            "spdi_proposed": "NC_000000.0:1000:A:T",
            "gene_proposed": "SYNGENE1",
            "hgvs_aliases": ()
        },
        proposed_claims=(),
        proposed_sources=(),
        retrieval_provenance=invalid_retrieval_pack
    )

    ctx = PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=lambda citation: True,
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "oracle-signoff-001",
        duplicate_index={}
    )

    with pytest.raises(AtlasSchemaError):
        validate_candidate_import(cand, ctx)


def test_successful_synthetic_promotion():
    """Verify successful synthetic candidate promotion returns accepted tuple and importer cannot write state."""
    try:
        from raptor.atlas.model import (
            AtlasCandidateImport, PromotionContext, DiseasePack, PackBinding
        )
        from raptor.atlas.promote import promote_candidate
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas promote/candidate_import implementation is missing")

    mock_pack = DiseasePack(
        schema="atlas.disease_pack.v1",
        pack_id="synthpack",
        pack_version="1.0.0",
        pack_content_hash="mock_hash",
        allowed_genes=("SYNGENE1",),
        assembly_pins=("GRCh38",),
        transcript_pins=(),
        reconciliation_policy={},
        ontology_extensions={
            "allowed_kinds": ("pathway",),
            "allowed_contexts": ("cell-assay-A",)
        },
        source_register_pins=(),
        prohibitions={},
        pilot_eval_metadata={}
    )

    ctx = PromotionContext(
        disease_pack=mock_pack,
        citation_resolver=lambda citation: True,
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "oracle-signoff-001",
        duplicate_index={}
    )

    cand_valid = AtlasCandidateImport(
        candidate_variant={
            "spdi_proposed": "NC_000000.0:1000:A:T",
            "gene_proposed": "SYNGENE1",
            "hgvs_aliases": ()
        },
        proposed_claims=({
            "claim_text": "synthetic assay signal C", "claim_kind_proposed": "pathway", "directionality": "increase",
            "source_ref_proposed": "lit-1",
            "span_proposed": {"locator": "L1", "exact_quote": "synthetic quote C", "page_or_figure": "1"}, "context_proposed": "cell-assay-A"
        },),
        proposed_sources=({
            "entry_id": "lit-1", "source_type": "PRIMARY-LIT", "role": "direct_evidence_leaf",
            "bib": {"pmid": "12345"}
        },),
        retrieval_provenance={
            "agents": (), "queries": (), "run_id": "r1", "retrieved_at": "now",
            "pack_binding": {
                "pack_id": "synthpack",
                "pack_version": "1.0.0",
                "pack_content_hash": "mock_hash"
            },
            "prompt_hash": "h", "bookshelf_version": "v1"
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


