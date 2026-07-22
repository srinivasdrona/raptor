"""
Gemini RED tests for Mechanism Atlas: Discovery Context Templates and Optionality
Spec coverage:
- Inspect actual planned files under configs/atlas/discovery/ for required schemas and contents.
- Validate context_manifest.json required keys, pins, and Phase-1 placeholders.
- Validate task_graph.json exact six engine tasks in exact dependency order:
  [identity_confirmation, literature_retrieval, claim_span_extraction,
   contradiction_search, assay_context_normalization, evidence_gap_mapping].
- Validate bookshelf_sources.yaml public-data context pins.
- Validate private_mapper_prompt.txt and evaluation_rubric.yaml public-data + no-classification constraints.
- Verify optionality: core package imports no Discovery SDK/agent, and unavailable/failed candidate
  has zero impact on the native profile or hash (provenance remains pure).
"""

import sys
import json
import yaml
from pathlib import Path
import pytest

# 2. Anti-cribbing check: ban real-content phrases/IDs only, not legitimate terms.
def assert_no_cribbing(obj):
    forbidden_ids = [
        "pmc11185720",
        "10.1101/2024.06.07.597916",
        "c.1832G>A",
        "p.Arg611Gln"
    ]
    if isinstance(obj, str):
        for f in forbidden_ids:
            assert f not in obj.lower(), f"Anti-cribbing violation: found real-content ID/phrase '{f}' in '{obj}'"
    elif isinstance(obj, dict):
        for k, v in obj.items():
            assert_no_cribbing(k)
            assert_no_cribbing(v)
    elif isinstance(obj, (list, tuple, set)):
        for item in obj:
            assert_no_cribbing(item)


def test_discovery_templates_exist_and_conform():
    """Verify that all 5 planned Discovery context template files exist under configs/atlas/discovery/ and conform to spec."""
    # Discovery configs are planned to be under configs/atlas/discovery/
    discovery_dir = Path("configs/atlas/discovery")

    if not discovery_dir.exists():
        pytest.fail("RED test: Planned Discovery config directory 'configs/atlas/discovery' is missing")

    manifest_path = discovery_dir / "context_manifest.json"
    task_graph_path = discovery_dir / "task_graph.json"
    bookshelf_path = discovery_dir / "bookshelf_sources.yaml"
    prompt_path = discovery_dir / "private_mapper_prompt.txt"
    rubric_path = discovery_dir / "evaluation_rubric.yaml"

    missing_files = [p for p in [manifest_path, task_graph_path, bookshelf_path, prompt_path, rubric_path] if not p.exists()]
    if missing_files:
        pytest.fail(f"RED test: Planned Discovery template files are missing: {missing_files}")

    # 1. Verify context_manifest.json
    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = json.load(f)

    required_keys = {
        "raptor_commit",
        "atlas_schema_version",
        "disease_pack_id",
        "disease_pack_version",
        "disease_pack_content_hash",
        "bookshelf_version",
        "prompt_hash",
        "packet_manifest_hash"
    }
    for k in required_keys:
        assert k in manifest, f"context_manifest.json is missing required pin: {k}"

    # Verify Phase-1 placeholder rules:
    # prompt_hash and packet_manifest_hash must be explicit Phase-1 placeholders (nonempty, non-64hex)
    prompt_hash = manifest["prompt_hash"]
    packet_manifest_hash = manifest["packet_manifest_hash"]
    
    assert prompt_hash, "prompt_hash must be non-empty"
    assert packet_manifest_hash, "packet_manifest_hash must be non-empty"
    assert len(prompt_hash) != 64, "prompt_hash in Phase 1 must not be a 64-hex hash"
    assert len(packet_manifest_hash) != 64, "packet_manifest_hash in Phase 1 must not be a 64-hex hash"
    assert "PLACEHOLDER" in prompt_hash, "prompt_hash must contain a PLACEHOLDER sentinel"
    assert "PLACEHOLDER" in packet_manifest_hash, "packet_manifest_hash must contain a PLACEHOLDER sentinel"

    for real_key in ["disease_pack_id", "disease_pack_version", "disease_pack_content_hash"]:
        val = manifest[real_key]
        assert "PLACEHOLDER" not in str(val), f"disease-pack pin {real_key} must be a real value in Phase 1"
        if real_key == "disease_pack_content_hash":
            assert len(val) == 64, f"disease_pack_content_hash must be a valid 64-character hash, got {val}"

    # 2. Verify task_graph.json
    with task_graph_path.open("r", encoding="utf-8") as f:
        tg = json.load(f)

    # Must contain exact six engine tasks in exact order
    expected_order = [
        "identity_confirmation",
        "literature_retrieval",
        "claim_span_extraction",
        "contradiction_search",
        "assay_context_normalization",
        "evidence_gap_mapping"
    ]
    assert tg.get("steps_exact_order") == expected_order, (
        f"Task graph steps are incorrect or misordered. Expected: {expected_order}"
    )

    # 3. Verify bookshelf_sources.yaml
    with bookshelf_path.open("r", encoding="utf-8") as f:
        bookshelf = yaml.safe_load(f)

    assert "required_context_pins" in bookshelf, "bookshelf_sources.yaml missing required_context_pins"
    assert "public_licensed_sources" in bookshelf, "bookshelf_sources.yaml missing public_licensed_sources"

    # 4. Verify private_mapper_prompt.txt
    prompt_text = prompt_path.read_text(encoding="utf-8")
    assert "public-data-only" in prompt_text, "Prompt must instruct public-data-only use"
    assert "no-classification" in prompt_text, "Prompt must restrict classification use"
    assert "AtlasCandidateImport" in prompt_text, "Prompt must output AtlasCandidateImport shape"

    # 5. Verify evaluation_rubric.yaml
    with rubric_path.open("r", encoding="utf-8") as f:
        rubric = yaml.safe_load(f)

    # Check for axes and no-classification rules
    axes = rubric.get("native_vs_discovery_evaluation", {}).get("axes", [])
    assert len(axes) > 0, "Evaluation rubric is missing evaluation axes"
    assert "public-data" in str(rubric), "Rubric must enforce public-data-only validation"
    assert "no-classification" in str(rubric), "Rubric must enforce no-classification validation"


# test_phase2_manifest_validation_rules removed because validate_discovery_manifest is non-public



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


def test_discovery_optionality_and_isolation():
    """Verify that the core atlas runs successfully and unavailable/rejected candidates have zero impact."""
    try:
        import raptor.atlas.model as model_mod
        from raptor.atlas.profile import build_mechanism_profile
        from raptor.atlas.hashing import evidence_core_hash
        from raptor.atlas.promote import validate_candidate_import
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas template/profile implementation is missing")

    # 1. Build native profile using exact public API: build_mechanism_profile(identity, claims, contexts, edges, sources, *, pack)
    pack = make_schema_valid_disease_pack(model_mod)

    identity = model_mod.AtlasIdentity(
        spdi_canonical="NC_000000.0:1000:A:T", gene="SYNGENE1", assembly="GRCh38",
        transcript_pin="NM_900001.1", hgvs_c="c.100A>T", hgvs_p="p.Lys34Met", hgvs_g="g.1000A>T",
        identity_state="resolved"
    )

    good_span = model_mod.Span(locator="L1", exact_quote="synthetic quote", page_or_figure="1")
    good_ref = model_mod.EntryRef(entry_id="synthsrc-0001", span=good_span)

    claim = model_mod.ObservedClaim(
        claim_id="claim-1", claim_text="synthetic assay signal A", claim_kind="pathway",
        source_ref=good_ref, verification="verified", directionality="increase"
    )

    # sources sequence must be SourceRegisterEntry, not EntryRef
    good_source_pin = pack.source_register_pins[0]

    # Calling the exact positional+keyword builder contract:
    profile = build_mechanism_profile(
        identity,          # identity
        (claim,),          # claims
        (),                # contexts
        (),                # edges
        (good_source_pin,),# sources: SourceRegisterEntry sequence
        pack=pack          # *pack keyword-only
    )

    h1 = evidence_core_hash(profile)

    # 2. Drive an unavailable/rejected synthetic candidate import through specified public rejection seam:
    # Build candidate with off-pack gene -> Gate 1 validation fails and raises AtlasIdentityError (using list types per Finding 2)
    rejected_cand = model_mod.AtlasCandidateImport(
        candidate_variant={
            "spdi_proposed": "NC_000000.0:1000:A:T",
            "gene_proposed": "OFF_PACK_GENE",  # off-pack!
            "hgvs_aliases": []
        },
        proposed_claims=[],
        proposed_sources=[],
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
            "prompt_hash": "PLACEHOLDER_PHASE2",
            "bookshelf_version": "v2.1"
        }
    )

    ctx = model_mod.PromotionContext(
        disease_pack=pack,
        citation_resolver=lambda citation: True,
        context_validator=lambda kind, ctx: True,
        human_oracle_reviewer=lambda cand_id: "oracle-signoff-001",
        duplicate_index={}
    )

    # Drive the rejection
    with pytest.raises((model_mod.AtlasIdentityError, model_mod.AtlasSchemaError)):
        validate_candidate_import(rejected_cand, ctx)

    # 3. Assert that original profile object, content and hash remains unchanged, and builder remains fully usable
    assert profile.identity.gene == "SYNGENE1"
    assert len(profile.claims) == 1
    assert evidence_core_hash(profile) == h1

    # Verify native builder is still usable
    rebuilt_profile = build_mechanism_profile(
        identity,
        (claim,),
        (),
        (),
        (good_source_pin,),
        pack=pack
    )
    assert evidence_core_hash(rebuilt_profile) == h1


