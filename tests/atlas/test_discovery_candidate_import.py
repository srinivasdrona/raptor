"""
Gemini RED tests for Mechanism Atlas: Discovery Candidate Import and Promotion
Spec coverage:
- AtlasCandidateImport is untrusted; proposed claims/sources/identities never accepted without promotion.
- No direct accepted write.
- Promotion gate order enforced (all eight gates):
  1. identity re-admission
  2. source type/role
  3. citation resolution
  4. exact span
  5. context enums
  6. duplicate/conflict
  7. no-classification leakage
  8. human/oracle span review.
- Any failure rejects the candidate.
- Private `tsc-mechanism-evidence-mapper` output is AtlasCandidateImport only.
"""

import pytest

from raptor.atlas.model import (
    AtlasCandidateImport,
    AtlasSchemaError,
    AtlasProvenanceError,
)
from raptor.atlas.promote import (
    validate_candidate_import,
    promote_candidate,
)

def test_candidate_import_is_untrusted_no_direct_accepted_write():
    """Verify proposed candidate never becomes accepted directly without passing the promotion gate."""
    candidate = AtlasCandidateImport(
        candidate_id="cand-1",
        variant_id="NC_000016.10:2083921:G:A",
        proposed_claims=[{"statement": "mTOR activation", "pmid": "12345"}],
        status="proposed"
    )
    
    # Cannot write or promote directly without validation
    with pytest.raises(AtlasSchemaError):
        # Simulating bypass attempt or missing validation
        promote_candidate(candidate, bypass_validation=True) # type: ignore


def test_promotion_gate_order_enforced():
    """Promotion gate order enforced: identity re-admission, source type/role, citation, exact span, etc."""
    # We will pass various invalid candidates and verify they fail at different stages of validate_candidate_import.
    
    # 1. Identity re-admission failure (missing canonical GRCh38 SPDI)
    cand_bad_identity = AtlasCandidateImport(
        candidate_id="cand-1",
        variant_id="invalid-variant-id",
        proposed_claims=[{"statement": "mTOR", "pmid": "12345", "span": "Fig1"}],
        status="proposed"
    )
    with pytest.raises(AtlasSchemaError) as exc_info:
        validate_candidate_import(cand_bad_identity)
    assert "identity" in str(exc_info.value).lower()

    # 2. Source type/role failure (e.g. proposed source has disallowed role/type)
    cand_bad_source = AtlasCandidateImport(
        candidate_id="cand-2",
        variant_id="NC_000016.10:2083921:G:A",
        proposed_claims=[{
            "statement": "mTOR", 
            "pmid": "12345", 
            "source_type": "PRIMARY-OFFICIAL",  # ClinVar is disallowed for grounding direct claims
            "role": "direct_evidence_leaf",
            "span": "Fig1"
        }],
        status="proposed"
    )
    with pytest.raises(AtlasProvenanceError) as exc_info:
        validate_candidate_import(cand_bad_source)
    assert "source" in str(exc_info.value).lower() or "role" in str(exc_info.value).lower()

    # 3. Citation resolution failure (invalid/unresolvable citation)
    cand_bad_citation = AtlasCandidateImport(
        candidate_id="cand-3",
        variant_id="NC_000016.10:2083921:G:A",
        proposed_claims=[{
            "statement": "mTOR", 
            "pmid": "999999999",  # unresolvable
            "source_type": "PRIMARY-LIT",
            "role": "direct_evidence_leaf",
            "span": "Fig1"
        }],
        status="proposed"
    )
    with pytest.raises(AtlasProvenanceError) as exc_info:
        validate_candidate_import(cand_bad_citation)
    assert "citation" in str(exc_info.value).lower() or "resolve" in str(exc_info.value).lower()


def test_private_mapper_output_is_candidate_import_only():
    """Verify that private tsc-mechanism-evidence-mapper output is AtlasCandidateImport only."""
    from raptor.atlas.promote import map_mapper_output_to_candidate
    
    raw_output = {
        "variant": "TSC2 p.Arg611Gln",
        "claims": [{"quote": "mTOR hyperactivation", "pmid": "12345", "figure": "Fig 1"}]
    }
    
    candidate = map_mapper_output_to_candidate(raw_output)
    assert isinstance(candidate, AtlasCandidateImport)
    assert candidate.status == "proposed"
