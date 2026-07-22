"""
Gemini RED tests for Mechanism Atlas: Disease Pack Loader and Validation
Spec coverage:
- load_disease_pack, validate_disease_pack, pack_content_hash interfaces.
- Positive fixture from spec parses, normalizes and digests to exact sha256 9fa764... and byte size 858.
- YAML formatting/comments do not affect hash; any participating value change changes hash.
- Invalid pack metadata, bad namespacing, or wrong role/type pairing raises AtlasPackError.
- TSC2 pack file/template path validation (fails closed in skeleton phase).
- Disease-literal core scan (src/raptor/atlas/ contains no vertical literals; fails if empty).
"""

import sys
import hashlib
import json
import yaml
import pytest
from pathlib import Path

# 2. Anti-cribbing rule: ban real-content phrases/IDs only, not ontology terms.
def assert_no_cribbing(obj):
    # Only ban actual real-content phrases/IDs, never general vocabulary terms.
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

FULL_FIXTURE_YAML = """
schema: atlas.disease_pack.v1
pack_id: synthpack
pack_version: 1.0.0
pack_content_hash: 9fa7643161ea0d8741ce8ffe0169f1f0109300a93c61cb5037cb86ca5abd7377
allowed_genes: [SYNGENE1]
assembly_pins: [GRCh38]
transcript_pins:
  - transcript: NM_900001.1
    requires: MANE-Select-verification
reconciliation_policy:
  alias_to_canonical_spdi_only: true
  no_fabrication: true
ontology_extensions:
  claim_kinds:
    - id: synthpack:pathway_synthpath
      parent: pathway
  node_layers: []
  mechanism_classes: []
  context_vocabularies:
    tissue: [synth_tissue_a]
source_register_pins:
  - entry_id: synthsrc-0001
    source_type: DATASET
    role: provenance_only
    urn_or_ids:
      accession: SYNTHDB-0001
    license: CC0-1.0
    verification: confirm_pending
prohibitions:
  no_hardcode_handoff_mechanism: true
pilot_eval_metadata:
  panel_strata: [synthetic_stratum_a]
  native_vs_discovery_axes: [reuse_percentage]
"""

def test_positive_fixture_hash_oracle():
    """Verify that the spec-provided positive fixture hashes and serializes to the exact specified outcomes."""
    # Ensure any real-content R611Q/PMID is absent from this test's synthetic fixture
    assert_no_cribbing(FULL_FIXTURE_YAML)

    # 1. Parse YAML
    manifest = yaml.safe_load(FULL_FIXTURE_YAML)
    assert manifest["schema"] == "atlas.disease_pack.v1"
    assert manifest["pack_id"] == "synthpack"
    assert manifest["pack_version"] == "1.0.0"

    # 2. Strip top-level pack_content_hash
    P = {k: v for k, v in manifest.items() if k != "pack_content_hash"}

    # 3. Canonical sort & serialize with separators=(",", ":") and ensure_ascii=False
    canonical_bytes = json.dumps(
        P, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")

    # 4. Assert exact byte length 858
    assert len(canonical_bytes) == 858, f"Expected length 858, got {len(canonical_bytes)}"

    # 5. Assert exact SHA-256 digest
    digest = hashlib.sha256(canonical_bytes).hexdigest()
    assert digest == "9fa7643161ea0d8741ce8ffe0169f1f0109300a93c61cb5037cb86ca5abd7377"


def test_yaml_formatting_independence():
    """Verify that YAML key order, formatting, and comments do not affect semantic hash computation."""
    reordered_yaml = """
# This is a comment
pack_version: 1.0.0
schema: atlas.disease_pack.v1
pack_id: synthpack
pack_content_hash: "different_hash_to_strip"
allowed_genes:
  - SYNGENE1
assembly_pins:
  - GRCh38
transcript_pins:
  - transcript: "NM_900001.1"
    requires: "MANE-Select-verification"
reconciliation_policy:
  alias_to_canonical_spdi_only: true
  no_fabrication: true
ontology_extensions:
  claim_kinds:
    - id: "synthpack:pathway_synthpath"
      parent: "pathway"
  node_layers: []
  mechanism_classes: []
  context_vocabularies:
    tissue:
      - synth_tissue_a
source_register_pins:
  - entry_id: synthsrc-0001
    source_type: DATASET
    role: provenance_only
    urn_or_ids:
      accession: SYNTHDB-0001
    license: CC0-1.0
    verification: confirm_pending
prohibitions:
  no_hardcode_handoff_mechanism: true
pilot_eval_metadata:
  panel_strata:
    - synthetic_stratum_a
  native_vs_discovery_axes:
    - reuse_percentage
"""
    m1 = yaml.safe_load(FULL_FIXTURE_YAML)
    m2 = yaml.safe_load(reordered_yaml)

    p1 = {k: v for k, v in m1.items() if k != "pack_content_hash"}
    p2 = {k: v for k, v in m2.items() if k != "pack_content_hash"}

    bytes1 = json.dumps(p1, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    bytes2 = json.dumps(p2, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    assert bytes1 == bytes2
    assert hashlib.sha256(bytes1).hexdigest() == hashlib.sha256(bytes2).hexdigest()


def test_hash_sensitivity():
    """Verify that any participating value, including optional created_at, changes the hash."""
    base_manifest = yaml.safe_load(FULL_FIXTURE_YAML)
    del base_manifest["pack_content_hash"]

    def get_hash(manifest_dict):
        b = json.dumps(manifest_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(b).hexdigest()

    original_hash = get_hash(base_manifest)

    # 1. Mutate pack_version
    m_mutated_version = yaml.safe_load(FULL_FIXTURE_YAML)
    del m_mutated_version["pack_content_hash"]
    m_mutated_version["pack_version"] = "1.0.1"
    assert get_hash(m_mutated_version) != original_hash

    # 2. Add optional created_at
    m_with_created_at = yaml.safe_load(FULL_FIXTURE_YAML)
    del m_with_created_at["pack_content_hash"]
    m_with_created_at["created_at"] = "2026-07-23T01:10:00Z"
    assert get_hash(m_with_created_at) != original_hash

    # 3. Mutate ontology extensions list order
    m_mutated_kinds = yaml.safe_load(FULL_FIXTURE_YAML)
    del m_mutated_kinds["pack_content_hash"]
    m_mutated_kinds["ontology_extensions"]["claim_kinds"] = [
        {"id": "synthpack:pathway_synthpath", "parent": "pathway"},
        {"id": "synthpack:pathway_another", "parent": "pathway"}
    ]
    assert get_hash(m_mutated_kinds) != original_hash


def test_load_and_validate_failures():
    """Verify load/validate disease pack failure and error typing."""
    try:
        from raptor.atlas.pack import validate_disease_pack
        from raptor.atlas.model import AtlasPackError
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas.pack implementation is missing")

    # validate_disease_pack on correct dict should pass
    manifest = yaml.safe_load(FULL_FIXTURE_YAML)
    validate_disease_pack(manifest)

    # 1. Missing required field raises AtlasPackError
    m_missing = yaml.safe_load(FULL_FIXTURE_YAML)
    del m_missing["allowed_genes"]
    with pytest.raises(AtlasPackError):
        validate_disease_pack(m_missing)

    # 2. Mis-namespaced ontology extension raises AtlasPackError
    m_bad_namespace = yaml.safe_load(FULL_FIXTURE_YAML)
    m_bad_namespace["ontology_extensions"]["claim_kinds"] = [
        {"id": "unnamespaced_kind", "parent": "pathway"}
    ]
    with pytest.raises(AtlasPackError):
        validate_disease_pack(m_bad_namespace)

    # 3. Parentless ontology extension raises AtlasPackError
    m_parentless = yaml.safe_load(FULL_FIXTURE_YAML)
    m_parentless["ontology_extensions"]["claim_kinds"] = [
        {"id": "synthpack:splicing_new"}  # no parent
    ]
    with pytest.raises(AtlasPackError):
        validate_disease_pack(m_parentless)

    # 4. Invalid source role/type pairing raises AtlasPackError
    m_bad_pairing = yaml.safe_load(FULL_FIXTURE_YAML)
    m_bad_pairing["source_register_pins"] = [
        {
            "entry_id": "pin-0001",
            "source_type": "PRIMARY-OFFICIAL",  # disallowed as a leaf grounding source
            "role": "direct_evidence_leaf",
            "urn_or_ids": {"accession": "A"},
            "verification": "verified"
        }
    ]
    with pytest.raises(AtlasPackError):
        validate_disease_pack(m_bad_pairing)


def test_tsc2_pack_existence():
    """Assert paths and template schema requirements for the tsc2 disease pack."""
    pack_path = Path("configs/atlas/packs/tsc2/pack.yaml")
    if not pack_path.exists():
        # This is expected to be RED in the planning/tests-first skeleton phase.
        pytest.fail("RED test: configs/atlas/packs/tsc2/pack.yaml does not exist.", pytrace=False)

    # Verify loading of actual tsc2 disease pack config file
    with pack_path.open("r", encoding="utf-8") as f:
        pack_manifest = yaml.safe_load(f)

    # Schema must match tsc2 pack specification
    assert pack_manifest["schema"] == "atlas.disease_pack.v1"
    assert pack_manifest["pack_id"] == "tsc2"
    assert "allowed_genes" in pack_manifest
    assert "TSC2" in pack_manifest["allowed_genes"]
    # Verify exact structure and that load_disease_pack succeeds
    try:
        from raptor.atlas.pack import load_disease_pack
    except (ImportError, ModuleNotFoundError):
        pytest.fail("RED test: raptor.atlas.pack implementation is missing")

    pack = load_disease_pack(str(pack_path))
    assert pack.pack_id == "tsc2"


def test_core_disease_literal_guard_scan():
    """Verify that src/raptor/atlas/ is condition-agnostic and contains no vertical literals."""
    core_dir = Path("src/raptor/atlas")
    if not core_dir.exists() or not any(core_dir.glob("**/*.py")):
        # Fail the scan if core directory or files do not exist (planned absence is RED).
        pytest.fail("RED test: src/raptor/atlas/ contains no files to scan.", pytrace=False)

    forbidden_literals = {
        "TSC1", "TSC2", "NM_000548.5", "NC_000016.10", "mTOR", "mTORC1", "R611Q", "pathway_mtorc1"
    }

    found_violations = []
    for p in core_dir.glob("**/*.py"):
        code = p.read_text(encoding="utf-8")
        # Parse AST to check string literals and names specifically
        import ast
        try:
            tree = ast.parse(code, filename=str(p))
        except SyntaxError as e:
            pytest.fail(f"Syntax error in core module {p}: {e}")

        for node in ast.walk(tree):
            # Check string constants
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for lit in forbidden_literals:
                    if lit.lower() in node.value.lower():
                        found_violations.append((p, node.lineno, f"Literal constant '{node.value}' matches '{lit}'"))
            # Check variable or attribute names
            elif isinstance(node, ast.Name):
                for lit in forbidden_literals:
                    if lit.lower() in node.id.lower():
                        found_violations.append((p, node.lineno, f"Name '{node.id}' matches '{lit}'"))

    if found_violations:
        violations_str = "\\n".join(f"{p}:{l} - {m}" for p, l, m in found_violations)
        pytest.fail(f"Core agnosticism boundary violated! Vertical literals found in src/raptor/atlas/:\\n{violations_str}")
