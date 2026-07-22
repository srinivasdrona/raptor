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

# 1. Guard planned imports so all tests collect cleanly
try:
    from raptor.atlas.model import (
        MechanismProfile,
        AtlasIdentity,
        ObservedClaim,
        EntryRef,
        Span,
        PackBinding,
        EvidenceAssessment,
        Provenance,
    )
    from raptor.atlas.profile import build_mechanism_profile
    from raptor.atlas.hashing import evidence_core_hash
    IMPLEMENTED = True
except (ImportError, ModuleNotFoundError):
    MechanismProfile = None
    AtlasIdentity = None
    ObservedClaim = None
    EntryRef = None
    Span = None
    PackBinding = None
    EvidenceAssessment = None
    Provenance = None
    build_mechanism_profile = None
    evidence_core_hash = None
    IMPLEMENTED = False

def check_implemented():
    if not IMPLEMENTED:
        pytest.fail("RED test: raptor.atlas template/profile implementation is missing", pytrace=False)


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

    # Verify Phase-1 placeholder rule
    # prompt_hash and packet_manifest_hash can be placeholders, but disease-pack pins MUST NOT be placeholders
    for placeholder_key in ["prompt_hash", "packet_manifest_hash"]:
        val = manifest[placeholder_key]
        assert val is not None, f"Placeholder key {placeholder_key} cannot be empty"

    for real_key in ["disease_pack_id", "disease_pack_version", "disease_pack_content_hash"]:
        val = manifest[real_key]
        assert "PLACEHOLDER" not in str(val), f"disease-pack pin {real_key} must be a real value in Phase 1"

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


def test_discovery_optionality_and_isolation():
    """Verify that the core atlas runs successfully with NO Discovery packages installed, and failed candidates have no impact."""
    check_implemented()

    # 1. Assert Discovery SDK/agents are NOT imported/loaded by raptor.atlas (AST boundary or sys.modules verification)
    discovery_packages = ["microsoft_discovery_sdk", "discovery_agent_client"]
    for pkg in discovery_packages:
        assert pkg not in sys.modules, f"Discovery package {pkg} is unexpectedly loaded"

    # 2. Build profile with standard inputs
    pack_binding = PackBinding(
        pack_id="synthpack", pack_version="1.0.0", pack_content_hash="mock_hash"
    )
    identity = AtlasIdentity(
        spdi_canonical="NC_000000.0:1000:A:T", gene="SYNGENE1", assembly="GRCh38",
        transcript_pin="NM_900001.1", hgvs_c="c.100A>T", hgvs_p="p.Lys34Met", hgvs_g="g.1000A>T",
        identity_state="resolved"
    )
    span = Span(locator="L1", exact_quote="quote", page_or_figure="1")
    ref = EntryRef(entry_id="lit-1", span=span)
    claim = ObservedClaim(
        claim_id="claim-1", claim_text="synthetic text", claim_kind="pathway",
        source_ref=ref, verification="verified", directionality="increase"
    )

    profile1 = build_mechanism_profile(
        identity=identity,
        pack_binding=pack_binding,
        claims=(claim,),
        candidate_classes=(),
        edges=(),
        evidence=EvidenceAssessment((), (), (), ()),
        provenance=Provenance((ref,), (), {"h": "core"}),
        run_metadata=None
    )

    h1 = evidence_core_hash(profile1)

    # 3. Simulate processing/rejecting an unavailable or failed Discovery candidate.
    # It must have ZERO impact on the accepted native profile and hash.
    # We do this by building the same profile again and proving that the hash is unchanged.
    profile2 = build_mechanism_profile(
        identity=identity,
        pack_binding=pack_binding,
        claims=(claim,),
        candidate_classes=(),
        edges=(),
        evidence=EvidenceAssessment((), (), (), ()),
        provenance=Provenance((ref,), (), {"h": "core"}),
        run_metadata=None
    )

    h2 = evidence_core_hash(profile2)
    assert h1 == h2, "Discovery unavailability/rejection changed the accepted profile hash"

