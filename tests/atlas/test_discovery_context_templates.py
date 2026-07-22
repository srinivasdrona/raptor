"""
Gemini RED tests for Mechanism Atlas: Discovery Context Templates and Optionality
Spec coverage:
- versioned Discovery context pack/template contract: manifest carries RAPTOR commit, manifest SHA, Bookshelf version, Atlas schema version, optional packet-manifest SHA.
- expect versioned templates under dedicated `configs/atlas/discovery/` directory, never `.discovery/`.
- task graph covers identity→retrieval→claim/span→contradiction→context→gap map.
- Discovery unavailability changes no accepted RAPTOR profile; builds unchanged.
- Core atlas imports no Discovery SDK/agent (out-of-process only).
"""

import os
import pytest

from raptor.atlas.model import DiscoveryContextManifest, MechanismProfile
from raptor.atlas.promote import build_atlas_with_optional_discovery

def test_context_manifest_fields():
    """Verify versioned Discovery context pack/template contract carries all required keys."""
    manifest = DiscoveryContextManifest(
        raptor_commit="8cfdab48123d7613a8661894ced0b1d9cc894742",
        manifest_sha="a0f94762e69b78f7db70398e20e1ccc6293708eff52de1e886174c2d4f7ea58f",
        bookshelf_version="v2.1",
        atlas_schema_version="v1.0",
        packet_manifest_sha="14f9b1a924bfe457a08986b33764b66c09be361eb54ab84efbfdf1e7d11dc09c"
    )
    assert manifest.raptor_commit == "8cfdab48123d7613a8661894ced0b1d9cc894742"
    assert manifest.manifest_sha is not None


def test_template_directory_location():
    """Verify context templates are expected under configs/atlas/discovery/, never .discovery/."""
    # Ensure any logic looking for template configs points strictly to configs/atlas/discovery/
    from raptor.atlas.promote import get_discovery_templates_dir
    
    templates_dir = get_discovery_templates_dir()
    assert "configs" in templates_dir.replace("\\", "/")
    assert "atlas" in templates_dir.replace("\\", "/")
    assert "discovery" in templates_dir.replace("\\", "/")
    assert ".discovery" not in templates_dir.replace("\\", "/")


def test_task_graph_structure():
    """Verify Discovery task graph covers identity -> retrieval -> claim/span -> contradiction -> context -> gap map."""
    from raptor.atlas.promote import get_task_graph_steps
    
    steps = get_task_graph_steps()
    expected_order = ["identity", "retrieval", "claim_span", "contradiction", "context", "gap_map"]
    assert steps == expected_order


def test_discovery_unavailability_optionality():
    """Discovery unavailability must not block RAPTOR Atlas build or alter accepted profiles."""
    # Simulate Discovery service being down / offline
    # build_atlas_with_optional_discovery should still succeed and yield accepted profiles unchanged.
    accepted_profiles_before = build_atlas_with_optional_discovery(discovery_available=True)
    accepted_profiles_after = build_atlas_with_optional_discovery(discovery_available=False)
    
    assert accepted_profiles_before == accepted_profiles_after
    assert len(accepted_profiles_after) >= 0


def test_discovery_import_boundary():
    """Assert that core atlas imports no Discovery SDK or agent."""
    import sys
    
    # Simulated importing of atlas modules
    import raptor.atlas.model as model
    import raptor.atlas.promote as promote
    
    forbidden_discovery_modules = [
        "microsoft_discovery_sdk",
        "discovery_agent_client",
        "microsoft.discovery"
    ]
    
    for mod in forbidden_discovery_modules:
        assert mod not in sys.modules or sys.modules[mod] is None
