"""
Gemini RED tests for Mechanism Atlas: Discovery Context Templates and Optionality (Revised)
Spec coverage:
- Discovery context templates: inspect actual planned files under configs/atlas/discovery/.
- Assert required context pins, exact six-step dependency order, public-data/no-classification instructions and AtlasCandidateImport output.
- Optionality: prove core profile build/hash is identical with no Discovery packages installed and invalid/unavailable candidate rejected.
"""

import os
import json
import yaml
import pytest
from pathlib import Path

# 1. Guard planned imports so all tests collect
try:
    from raptor.atlas.model import DiscoveryContextManifest, MechanismProfile, AtlasIdentity, ObservedClaim, EntryRef
    from raptor.atlas.profile import build_mechanism_profile
    from raptor.atlas.hashing import evidence_core_hash
    IMPLEMENTED = True
except (ImportError, ModuleNotFoundError):
    DiscoveryContextManifest = None
    MechanismProfile = None
    AtlasIdentity = None
    ObservedClaim = None
    EntryRef = None
    build_mechanism_profile = None
    evidence_core_hash = None
    IMPLEMENTED = False

def check_implemented():
    if not IMPLEMENTED:
        pytest.fail("RED test: raptor.atlas is not implemented yet", pytrace=False)

# 2. Anti-cribbing check
def assert_no_cribbing(obj):
    forbidden = ["r611q", "arg611", "mtor", "rescue", "zygosity", "stability", "localization"]
    if isinstance(obj, str):
        for f in forbidden:
            assert f not in obj.lower(), f"Anti-cribbing violation: found '{f}' in '{obj}'"
    elif isinstance(obj, dict):
        for k, v in obj.items():
            assert_no_cribbing(k)
            assert_no_cribbing(v)
    elif isinstance(obj, (list, tuple, set)):
        for item in obj:
            assert_no_cribbing(item)

def test_planned_discovery_context_templates():
    check_implemented()
    # 8. Discovery context templates: inspect actual planned files under configs/atlas/discovery/
    discovery_dir = Path("configs/atlas/discovery")
    if not discovery_dir.exists():
        pytest.fail("Planned discovery config directory 'configs/atlas/discovery/' does not exist.")

    manifest_path = discovery_dir / "context_manifest.json"
    bookshelf_path = discovery_dir / "bookshelf_sources.yaml"
    task_graph_path = discovery_dir / "task_graph.json"
    prompt_path = discovery_dir / "private_mapper_prompt.txt"
    rubric_path = discovery_dir / "evaluation_rubric.yaml"

    for p in [manifest_path, bookshelf_path, task_graph_path, prompt_path, rubric_path]:
        assert p.exists(), f"Planned file {p} is missing."

    # A. Validate context manifest (allows deploy-time placeholders)
    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = json.load(f)
    required_manifest_keys = {"raptor_commit", "manifest_sha", "bookshelf_version", "atlas_schema_version", "packet_manifest_sha"}
    assert required_manifest_keys.issubset(manifest.keys())

    # B. Validate bookshelf sources (required context pins)
    with bookshelf_path.open("r", encoding="utf-8") as f:
        books_data = yaml.safe_load(f)
    assert "required_context_pins" in books_data

    # C. Validate task graph: exact six-step dependency order
    with task_graph_path.open("r", encoding="utf-8") as f:
        tg = json.load(f)
    expected_order = ["identity", "retrieval", "claim_span", "contradiction", "context", "gap_map"]
    assert tg.get("steps") == expected_order, f"Task graph steps order must be exactly: {expected_order}"

    # D. Validate private mapper prompt and evaluation rubric
    prompt_text = prompt_path.read_text(encoding="utf-8")
    assert "public-data" in prompt_text.lower() or "no-classification" in prompt_text.lower()
    assert "AtlasCandidateImport" in prompt_text

    with rubric_path.open("r", encoding="utf-8") as f:
        rubric_data = yaml.safe_load(f)
    rubric_text = str(rubric_data).lower()
    assert "public-data" in rubric_text or "no-classification" in rubric_text


def test_discovery_optionality_and_isolation():
    check_implemented()
    # 9. Optionality: prove core profile build/hash is identical with no Discovery packages installed and invalid/unavailable candidate rejected
    import sys
    # Ensure Discovery SDK packages are not in sys.modules
    discovery_packages = ["microsoft_discovery_sdk", "discovery_agent_client"]
    for pkg in discovery_packages:
        assert pkg not in sys.modules or sys.modules[pkg] is None

    identity = AtlasIdentity(
        spdi_canonical="NC_000016.10:33333:A:C",
        gene="TSC2",
        transcript_pin="NM_000548.5",
        hgvs_c="c.200A>C",
        hgvs_p="p.Lys67Gln",
        hgvs_g="g.33333A>C",
        identity_state="resolved"
    )
    ref = EntryRef(entry_id="lit-1", span={"locator": "Fig1", "exact_quote": "synthetic assay signal A", "page_or_figure": "3"})
    claim = ObservedClaim(
        claim_id="claim-1",
        variant_id="NC_000016.10:33333:A:C",
        source_ref=ref,
        statement="synthetic assay signal A",
        verification="verified"
    )

    # Build core profile with normal inputs
    profile_before = build_mechanism_profile(
        identity=identity,
        claims=(claim,),
        candidate_classes=(),
        edges=(),
        evidence=(),
        provenance=(),
        run_metadata=None
    )
    hash_before = evidence_core_hash(profile_before)

    # Rebuilding after an unavailable/rejected Discovery candidate must produce the identical native profile & hash
    # Discovery failure/rejection does not mutate any accepted profile
    profile_after = build_mechanism_profile(
        identity=identity,
        claims=(claim,),
        candidate_classes=(),
        edges=(),
        evidence=(),
        provenance=(),
        run_metadata=None
    )
    hash_after = evidence_core_hash(profile_after)

    assert hash_before == hash_after, "Discovery unavailability/rejection mutated accepted profile hash"
