import os
import sys
import hashlib
import json
from pathlib import Path
import pytest
import yaml

# Bootstrapping src relative to this file's location
src_path = Path(__file__).resolve().parent.parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

# Import RAPTOR components
from raptor.scorer.bias_source import BiasTsvSource
from raptor.scorer.contract import BiasContractError

# 14 files present_hashed in arm_inventory
ARM_INVENTORY = [
    {
        "id": "sample_nirvana_json",
        "path": os.path.join("devbox-artifacts", "sample_tsc_nirvana.json.gz"),
        "sha256": "24c8083f01d46a4dca2233abeaaf639b7f7ccde7378d90b8b087e9f5ec250bca",
        "bytes": 14360,
    },
    {
        "id": "required_paths_local",
        "path": os.path.join("devbox-artifacts", "hg38_nirvana_required_paths.local.json"),
        "sha256": "5d57c068d44a00ce0d95215046b215f9a4fa6eae35b4629e39cfbcce8010af32",
        "bytes": 1301,
    },
    {
        "id": "required_paths_masked",
        "path": os.path.join("handoffs", "masked-heldout-2026-07-12", "return-post-pm1-resume", "hg38_nirvana_required_paths.masked.json"),
        "sha256": "6c05b8c30efa4f6032a3a40446823a0e08c888295889d3876cf7871d5b4f569c",
        "bytes": 1649,
    },
    {
        "id": "evaluation_skip_list",
        "path": os.path.join("handoffs", "masked-heldout-2026-07-12", "return-post-pm1-resume", "evaluation_skip_list.txt"),
        "sha256": "bb418c11773080d8cf6b3facadf71236d25ce35fa2ca173d63d33089c57a1d8a",
        "bytes": 20,
    },
    {
        "id": "masked_ps1_pm5",
        "path": os.path.join("handoffs", "masked-heldout-2026-07-12", "return-post-pm1-resume", "hg38_PS1_PM5_clinvar_pathogenic_aa_nirvana.tsv"),
        "sha256": "f17b19e6322ac00ad1bae5125efc6381874266771fa71fdb9832b3a54401be1f",
        "bytes": 28395992,
    },
    {
        "id": "masked_pp2",
        "path": os.path.join("handoffs", "masked-heldout-2026-07-12", "return-post-pm1-resume", "hg38_PP2_missense_pathogenic_genes.tsv"),
        "sha256": "43f6002d8c88cbc200df4da79aeffb52d1f854589aeb50c97e190b80c376d2cf",
        "bytes": 34786,
    },
    {
        "id": "masked_bp1",
        "path": os.path.join("handoffs", "masked-heldout-2026-07-12", "return-post-pm1-resume", "hg38_BP1_truncating_genes.tsv"),
        "sha256": "274ab0ce632ef6d14b5fefe4a87c04a4955e1685569ad45a73d06f5a78fd5840",
        "bytes": 1855,
    },
    {
        "id": "masked_pm1",
        "path": os.path.join("handoffs", "masked-heldout-2026-07-12", "return-post-pm1-resume", "hg38_PM1_chrom_to_pathogenic_domain_list.tsv"),
        "sha256": "ce9ee18d89f208f409dff66532590d7e7294a690cb631ffe2b1399acfe2409ee",
        "bytes": 1587498,
    },
    {
        "id": "return_manifest",
        "path": os.path.join("handoffs", "masked-heldout-2026-07-12", "return-post-pm1-resume", "RETURN_MANIFEST.sha256.txt"),
        "sha256": "5efdccdc57f7d2bdf774486dfbde106ab173bf87412c6db103aaba9958d9ac91",
        "bytes": 4005,
    },
    {
        "id": "masked_bias_tsv",
        "path": os.path.join("handoffs", "masked-heldout-2026-07-12", "return-post-pm1-resume", "holdout_input.masked.bias_output.tsv"),
        "sha256": "7eece438a880e0c6a591df62e231bc93848eeb42277a2f4360983914298fc512",
        "bytes": 2590498,
    },
    {
        "id": "scoring_report",
        "path": os.path.join("handoffs", "masked-heldout-2026-07-12", "return-post-pm1-resume", "MASKED_HELDOUT_SCORING_REPORT.md"),
        "sha256": "e5351a42e3120083d21d6b82775a38aee2a5d9bcf8586da08b3b239f24c35b3c",
        "bytes": 5039,
    },
    {
        "id": "holdout_input_vcf",
        "path": os.path.join("handoffs", "masked-heldout-2026-07-12", "inputs", "holdout_input.vcf"),
        "sha256": "4dcba7c882b65838cedf8ce0ad56e0f7764df34b247ab412aac144d4027c622d",
        "bytes": 69470,
    },
    {
        "id": "holdout_input_provenance",
        "path": os.path.join("handoffs", "masked-heldout-2026-07-12", "inputs", "holdout_input.provenance.json"),
        "sha256": "63f1881287f1e3aa0b36ca14e1a7329ef2bcacc7b9674c2489f5e1d4352a6ac8",
        "bytes": 573,
    },
    {
        "id": "holdout_input_manifest",
        "path": os.path.join("handoffs", "masked-heldout-2026-07-12", "inputs", "holdout_input.manifest.jsonl"),
        "sha256": "9e588cdf8ebaea2e3793e0ea74721ab5283b57c2abf045dbf3070cb6e81ec9e4",
        "bytes": 321687,
    }
]

EXPECTED_SOURCES = [
    {"name": "VEP", "version": "91", "release_date": "2017-12-18"},
    {"name": "MultiZ100Way", "version": "20171006", "release_date": "2017-10-06"},
    {"name": "AlphaMissense", "version": "AlphaMissense_hg38.nirvana.tsv", "release_date": "2026-02-25"},
    {"name": "ClinVar", "version": "2026-02", "release_date": "2026-02-24"},
    {"name": "ClinVar", "version": "20240301", "release_date": "2024-03-01"},
    {"name": "dbSNP", "version": "156", "release_date": "2023-09-28"},
    {"name": "dbSNP", "version": "151", "release_date": "2018-04-18"},
    {"name": "GME", "version": "20160618", "release_date": "2016-06-18"},
    {"name": "gnomAD", "version": "4.0", "release_date": "2024-02-17"},
    {"name": "gnomAD_exome", "version": "4.0", "release_date": "2024-02-17"},
    {"name": "MITOMAP", "version": "20200819", "release_date": "2020-08-19"},
    {"name": "1000 Genomes Project", "version": "Phase 3 v3plus", "release_date": "2013-05-27"},
    {"name": "REVEL", "version": "20200205", "release_date": "2020-02-05"},
    {"name": "TOPMed", "version": "freeze_5", "release_date": "2017-08-28"},
    {"name": "ClinGen", "version": "20160414", "release_date": "2016-04-14"},
    {"name": "ClinGen Dosage Sensitivity Map", "version": "20240110", "release_date": "2024-01-10"},
    {"name": "DECIPHER", "version": "201509", "release_date": "2015-09-01"},
    {"name": "gnomAD_SV", "version": "4.0", "release_date": "2024-02-26"},
    {"name": "MITOMAP_SV", "version": "20200819", "release_date": "2020-08-19"},
    {"name": "1000 Genomes Project (SV)", "version": "Phase 3 v5a", "release_date": "2013-05-27"},
    {"name": "FusionCatcher", "version": "1.33", "release_date": "2020-12-22"},
    {"name": "DANN", "version": "20200205", "release_date": "2020-02-05"},
    {"name": "Gerp", "version": "20110522", "release_date": "2011-05-22"},
    {"name": "ClinGen disease validity curations", "version": "20240110", "release_date": "2024-01-10"},
    {"name": "gnomAD_gene_scores", "version": "4.0", "release_date": "2024-03-20"},
    {"name": "phyloP", "version": "hg38", "release_date": "2015-04-17"},
    {"name": "gnomAD_LCR", "version": "2.1", "release_date": "2019-04-10"},
    {"name": "MitochondrialHeteroplasmy", "version": "20180410", "release_date": "2020-05-21"}
]

MANIFEST_PATH = Path("configs/eval/core_annotation_bundle.yaml")
REF_PATH = Path("docs/reference/core-annotation-bundle-2026-07.md")


def compute_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def load_manifest():
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(f"Canonical manifest not found: {MANIFEST_PATH}")
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_reference():
    if not REF_PATH.exists():
        raise FileNotFoundError(f"Human reference docs not found: {REF_PATH}")
    with open(REF_PATH, "r", encoding="utf-8") as f:
        return f.read()


def check_file_entry_shape(entry):
    required_keys = {"id", "location", "path", "sha256", "bytes", "presence"}
    allowed_optional = {"attributes"}
    entry_keys = set(entry.keys())
    
    # Reject keys outside required + allowed_optional
    forbidden_keys = entry_keys - (required_keys | allowed_optional)
    assert not forbidden_keys, f"File entry contains forbidden keys: {forbidden_keys}"
    assert "worker_only" not in entry_keys, "File entry contains forbidden worker_only key"
    
    # Check all required keys are present
    missing_keys = required_keys - entry_keys
    assert not missing_keys, f"File entry is missing required keys: {missing_keys}"
    
    loc = entry["location"]
    pres = entry["presence"]
    sha = entry["sha256"]
    size = entry["bytes"]
    path = entry["path"]
    
    # Enums
    assert loc == "arm", f"Invalid location: {loc}. Location must be arm."
    assert pres == "present_hashed", f"Invalid presence: {pres}. Presence must be present_hashed."
    
    # Check sha256 is 64 lowercase hex
    assert len(sha) == 64 and all(c in "0123456789abcdef" for c in sha), f"Invalid sha256: {sha}"
    # Check bytes is a positive integer
    assert isinstance(size, int) and size > 0, f"Invalid bytes: {size}"
    
    # Reject any x64 path
    assert "x64" not in path.lower(), f"Path contains x64: {path}"
    
    # Check entry-specific extras live only under attributes
    forbidden_direct_extras = {"rows", "duplicate_ids", "contents", "role", "needed_for", "provenance_path"}
    found_extras = entry_keys & forbidden_direct_extras
    assert not found_extras, f"File entry has direct extras outside attributes: {found_extras}"
    
    if "attributes" in entry:
        attrs = entry["attributes"]
        assert isinstance(attrs, dict), "attributes must be a dict"
        assert "worker_only" not in attrs, "attributes contains worker_only key"
        assert "x64" not in str(attrs).lower(), "attributes contains x64 reference"


def check_x64_requirement_shape(item):
    required_keys = {"id", "kind", "x64_path", "expected_sha256", "expected_bytes", "required_for", "verification_rule"}
    assert set(item.keys()) == required_keys, f"x64 requirement keys mismatch. Got {set(item.keys())}"
    
    kind = item["kind"]
    assert kind in ["file", "directory", "manifest"], f"Invalid kind: {kind}"
    
    sha = item["expected_sha256"]
    if sha is not None:
        assert isinstance(sha, str)
        assert len(sha) == 64 and all(c in "0123456789abcdef" for c in sha), f"Invalid expected_sha256: {sha}"
        
    bytes_val = item["expected_bytes"]
    if bytes_val is not None:
        assert isinstance(bytes_val, int) and bytes_val > 0, f"Invalid expected_bytes: {bytes_val}"


# ==========================================
# Always-On Offline Tests (OFF1 - OFF9)
# ==========================================

def test_OFF1_schema():
    manifest = load_manifest()
    ref_content = load_reference()
    
    assert manifest.get("schema") == "raptor-core-annotation-bundle-manifest-v1", "Incorrect schema identifier"
    assert manifest.get("status") == "pinned_historical_evidence", "Incorrect status value"
    
    # Exact 14 top-level keys
    expected_top_keys = {
        "schema", "status", "readiness", "runtime", "data_sources", "structured_fields",
        "arm_inventory", "historical_run_attestation", "current_x64_reannotation_readiness",
        "pp3_bp4_suppression_prerequisite", "reuse_vs_reannotate", "licensing",
        "deferred_upgrades", "x64_handoff_requirements"
    }
    actual_top_keys = set(manifest.keys())
    assert actual_top_keys == expected_top_keys, f"Manifest keys mismatch: missing {expected_top_keys - actual_top_keys}, extra {actual_top_keys - expected_top_keys}"
    
    # Under readiness
    readiness = manifest.get("readiness", {})
    assert set(readiness.keys()) == {"reuse_readiness", "reannotation_readiness", "licensing_readiness"}
    
    assert readiness.get("reuse_readiness") == "BLOCKED_POLICY_IMPLEMENTATION", "Incorrect reuse_readiness enum"
    assert readiness.get("reannotation_readiness") == "X64_WORKER_UNVERIFIED_UNTIL_OPERATOR_MAKES_AVAILABLE", "Incorrect reannotation_readiness enum"
    assert readiness.get("licensing_readiness") == "PENDING_PERMITTED_USE_REVIEW", "Incorrect licensing_readiness enum"
    
    # Assert human reference mirrors the manifest
    assert "raptor-core-annotation-bundle-manifest-v1" in ref_content, "Human reference must mention manifest schema id"
    assert "pinned_historical_evidence" in ref_content, "Human reference must mention manifest status"
    assert "BLOCKED_POLICY_IMPLEMENTATION" in ref_content, "Human reference must mention reuse state is BLOCKED_POLICY_IMPLEMENTATION"
    assert "X64_WORKER_UNVERIFIED_UNTIL_OPERATOR_MAKES_AVAILABLE" in ref_content, "Human reference must mention reannotation state"
    assert "PENDING_PERMITTED_USE_REVIEW" in ref_content, "Human reference must mention licensing state"
    assert "historical evidence is pinned" in ref_content or "pinned" in ref_content.lower(), "Human reference must state historical evidence is pinned"
    assert "reuse is blocked" in ref_content.lower(), "Human reference must state reuse is blocked"
    assert "unverified" in ref_content.lower() or "unverified_until_operator_makes_available" in ref_content.lower(), "Human reference must state x64 reannotation is unverified"
    assert "raw-predictor-score permissions are pending permitted-use review" in ref_content.lower() or "pending_permitted_use_review" in ref_content.lower(), "Human reference must state raw score permissions are pending review"


def test_OFF2_source_values_28():
    manifest = load_manifest()
    sources = manifest.get("data_sources", [])
    
    assert len(sources) == 28, f"Expected exactly 28 sources, got {len(sources)}"
    
    # Closed shape for each source entry
    required_keys = {"name", "version", "release_date"}
    for idx, s in enumerate(sources):
        assert set(s.keys()) == required_keys, f"Source entry {idx} has incorrect keys: {set(s.keys())}"
    
    # Check exact equality (order-independent)
    def sort_key(s):
        return (s.get("name", ""), s.get("version", ""), s.get("release_date", ""))
        
    sorted_expected = sorted(EXPECTED_SOURCES, key=sort_key)
    sorted_actual = sorted(sources, key=sort_key)
    
    assert sorted_actual == sorted_expected, "Deployed data sources do not match the expected 28-source set exactly"


def test_OFF3_presence_enums():
    manifest = load_manifest()
    
    # 1. arm_inventory exact keys are data_root and present_hashed
    inventory = manifest.get("arm_inventory", {})
    assert set(inventory.keys()) == {"data_root", "present_hashed"}
    assert "worker_only" not in inventory, "arm_inventory contains forbidden worker_only key"
    
    present_hashed = inventory.get("present_hashed", [])
    assert len(present_hashed) == 14, f"Expected exactly 14 present_hashed files, got {len(present_hashed)}"
    
    # 2. Check shapes of all entries
    for item in present_hashed:
        check_file_entry_shape(item)
        
    # 3. Assert NO x64 path appears anywhere in arm_inventory
    inv_str = str(inventory)
    assert "x64" not in inv_str.lower(), "Found x64 path inside arm_inventory!"
    
    # 4. Validate x64_handoff_requirements exact closed shape and its 6 items
    handoff = manifest.get("x64_handoff_requirements", {})
    expected_handoff_keys = {"items", "bundle_presence_proof", "reannotation_commands_reference", "return_handoff_manifest", "required_artifact"}
    assert set(handoff.keys()) == expected_handoff_keys, f"x64_handoff_requirements keys mismatch. Got {set(handoff.keys())}"
    assert handoff.get("required_artifact") == "x64_bundle_verification.json", f"Invalid required_artifact: {handoff.get('required_artifact')}"
    
    items = handoff.get("items", [])
    assert len(items) == 6, f"Expected exactly 6 handoff requirement items, got {len(items)}"
    
    for item in items:
        check_x64_requirement_shape(item)
        
    # The list of IDs of these 6 entries must be exactly the 6 required IDs
    expected_ids = {"heldout_nirvana_json", "nirvana_data_root", "bias_data_root", "nirvana_full_manifest", "nirvana_updates_manifest", "bias_data_manifest"}
    actual_ids = {item["id"] for item in items}
    assert actual_ids == expected_ids, f"x64 handoff requirement IDs mismatch: expected {expected_ids}, got {actual_ids}"


def test_OFF4_reuse_blocked_on_suppression():
    manifest = load_manifest()
    readiness = manifest.get("readiness", {})
    
    # Reuse route must resolve to BLOCKED_POLICY_IMPLEMENTATION, never GO_REUSE
    assert readiness.get("reuse_readiness") == "BLOCKED_POLICY_IMPLEMENTATION"
    
    # Check PP3_BP4_SUPPRESSION_CONTRACT_REQUIRED or similar is required
    suppression_req = manifest.get("pp3_bp4_suppression_prerequisite", {})
    assert suppression_req.get("id") == "PP3_BP4_SUPPRESSION_CONTRACT_REQUIRED"


def test_OFF5_licensing_egress_flags():
    manifest = load_manifest()
    licensing = manifest.get("licensing", {})
    
    # Required keys under licensing
    expected_lic_keys = {"model", "historical_execution_observed", "channels", "downstream_use_rule", "cloud_egress_rule", "per_source"}
    assert set(licensing.keys()) == expected_lic_keys, f"Licensing keys mismatch: expected {expected_lic_keys}, got {set(licensing.keys())}"
    
    assert licensing.get("model") == "fail_closed"
    assert licensing.get("historical_execution_observed") is True
    
    channels = licensing.get("channels", {})
    assert set(channels.keys()) == {"local_execution_status", "raw_public_redistribution", "raw_cloud_egress"}
    assert channels.get("local_execution_status") == "pending_permitted_use_review"
    assert channels.get("raw_public_redistribution") is False
    assert channels.get("raw_cloud_egress") is False
    
    per_source = licensing.get("per_source", {})
    assert set(per_source.keys()) == {"revel", "alphamissense"}
    
    revel = per_source.get("revel", {})
    assert set(revel.keys()) == {"local_status", "raw_public_redistribution", "raw_cloud_egress"}
    assert revel.get("local_status") == "pending_permitted_use_review"
    assert revel.get("raw_public_redistribution") is False
    assert revel.get("raw_cloud_egress") is False
    
    alphamissense = per_source.get("alphamissense", {})
    assert set(alphamissense.keys()) == {"local_status", "raw_public_redistribution", "raw_cloud_egress", "licence_version"}
    assert alphamissense.get("local_status") == "pending_permitted_use_review"
    assert alphamissense.get("raw_public_redistribution") is False
    assert alphamissense.get("raw_cloud_egress") is False
    assert alphamissense.get("licence_version") == "confirm_pending"
    
    # Recursive walk check to fail if any boolean is True (except historical_execution_observed),
    # or any status field is outside its allowed set, or any value asserts permission.
    def check_node_recursively(node, key_name=None):
        if isinstance(node, dict):
            for k, v in node.items():
                check_node_recursively(v, k)
        elif isinstance(node, list):
            for item in node:
                check_node_recursively(item, key_name)
        elif isinstance(node, bool):
            # historical_execution_observed is allowed to be True, all other booleans must be False
            if key_name == "historical_execution_observed":
                assert node is True, "historical_execution_observed must be True"
            else:
                assert node is False, f"Forbidden True boolean value found at {key_name}"
        elif isinstance(node, str):
            # Allowed string statuses
            if key_name in ["local_execution_status", "local_status", "status"]:
                assert node == "pending_permitted_use_review", f"Forbidden status value '{node}' at {key_name}"
            elif key_name == "licence_version":
                assert node == "confirm_pending", f"Forbidden licence_version value '{node}'"
            else:
                # Any other string value must not assert currently permitted or allowed egress
                lower_val = node.lower()
                if "permitted" in lower_val:
                    assert "pending" in lower_val or "pending_permitted_use_review" in lower_val, f"Forbidden permissive phrasing: '{node}'"
                if "egress" in lower_val:
                    assert "false" in lower_val or "deny" in lower_val or "pending" in lower_val, f"Forbidden egress phrasing: '{node}'"
                    
    check_node_recursively(licensing)


def test_OFF6_deferred_upgrade_guard():
    manifest = load_manifest()
    sources = manifest.get("data_sources", [])
    
    for s in sources:
        name = s.get("name", "")
        ver = s.get("version", "")
        if name == "MANE" and "1.5" in ver:
            pytest.fail("MANE 1.5 is forbidden in this rerun")
        if name == "dbNSFP" and "5." in ver:
            pytest.fail("dbNSFP 5.x is forbidden in this rerun")
        if name == "gnomAD" and "4.1.1" in ver:
            pytest.fail("gnomAD 4.1.1 is forbidden in this rerun")
        if name == "dbSNP" and "157" in ver:
            pytest.fail("dbSNP 157 is forbidden in this rerun")
        if name == "RepeatMasker":
            pytest.fail("RepeatMasker is forbidden in this rerun")
        if name == "ClinVar" and ver > "2026-02":
            pytest.fail(f"Newer primary ClinVar {ver} is forbidden in this rerun")


def test_OFF7_structured_path_contract():
    manifest = load_manifest()
    fields = manifest.get("structured_fields", {})
    
    assert set(fields.keys()) == {"revel", "alphamissense", "scalars", "forbidden_source"}
    
    revel = fields.get("revel", {})
    assert revel.get("json_path") == "positions[].variants[].revel.score"
    assert revel.get("value_type") == "float"
    
    alphamissense = fields.get("alphamissense", {})
    assert alphamissense.get("json_path") == "positions[].variants[].AlphaMissense.AM_score"
    assert alphamissense.get("value_type") == "float"
    
    # Reject BIAS-rationale REVEL path
    assert "rationale" not in str(fields).lower()


def test_OFF8_revel_label_guard():
    manifest = load_manifest()
    sources = manifest.get("data_sources", [])
    
    revel_ver = None
    for s in sources:
        if s.get("name") == "REVEL":
            revel_ver = s.get("version")
            
    assert revel_ver == "20200205", f"Expected REVEL version 20200205, got {revel_ver}"


def test_OFF9_historical_vs_current_split():
    manifest = load_manifest()
    
    hist = manifest.get("historical_run_attestation", {})
    assert set(hist.keys()) == {"claim", "proven_by", "hashes", "independent_of"}
    assert hist.get("independent_of") == "current_x64_reannotation_readiness"
    
    hashes = hist.get("hashes", {})
    expected_hashes_keys = {
        "input_vcf_sha256", "provenance_sha256", "provenance_manifest_hash", "provenance_vcf_hash",
        "return_manifest_sha256", "scoring_report_sha256", "bias_tsv_sha256", "heldout_nirvana_json_sha256"
    }
    assert set(hashes.keys()) == expected_hashes_keys, f"Historical hashes keys mismatch: expected {expected_hashes_keys}, got {set(hashes.keys())}"
    
    # Assert exact pinned hash values
    assert hashes.get("input_vcf_sha256") == '4dcba7c882b65838cedf8ce0ad56e0f7764df34b247ab412aac144d4027c622d'
    assert hashes.get("provenance_sha256") == '63f1881287f1e3aa0b36ca14e1a7329ef2bcacc7b9674c2489f5e1d4352a6ac8'
    assert hashes.get("provenance_manifest_hash") == '9e588cdf8ebaea2e3793e0ea74721ab5283b57c2abf045dbf3070cb6e81ec9e4'
    assert hashes.get("provenance_vcf_hash") == '4dcba7c882b65838cedf8ce0ad56e0f7764df34b247ab412aac144d4027c622d'
    assert hashes.get("return_manifest_sha256") == '5efdccdc57f7d2bdf774486dfbde106ab173bf87412c6db103aaba9958d9ac91'
    assert hashes.get("scoring_report_sha256") == 'e5351a42e3120083d21d6b82775a38aee2a5d9bcf8586da08b3b239f24c35b3c'
    assert hashes.get("bias_tsv_sha256") == '7eece438a880e0c6a591df62e231bc93848eeb42277a2f4360983914298fc512'
    assert hashes.get("heldout_nirvana_json_sha256") == '315e601cc9ede55c07c4a59de796c2be5cf0f2827e441101ceea236390675d13'
    
    # Strict independence from current x64 readiness (no references in hist except independent_of)
    hist_str = str({k: v for k, v in hist.items() if k != "independent_of"})
    assert "current_x64" not in hist_str.lower(), "historical_run_attestation has current x64 dependency outside independent_of"
    
    curr = manifest.get("current_x64_reannotation_readiness", {})
    assert set(curr.keys()) == {"required_only_for", "status", "x64_requirement_ids", "presence_proof_when_needed", "boundary_rule"}
    assert curr.get("required_only_for") == "X64_REANNOTATE"
    
    # x64_requirement_ids matches exactly the 6 required IDs
    req_ids = curr.get("x64_requirement_ids", [])
    assert isinstance(req_ids, list), "x64_requirement_ids must be a list"
    assert len(req_ids) == 6, f"Expected exactly 6 requirement IDs, got {len(req_ids)}"
    expected_ids = {"heldout_nirvana_json", "nirvana_data_root", "bias_data_root", "nirvana_full_manifest", "nirvana_updates_manifest", "bias_data_manifest"}
    assert set(req_ids) == expected_ids, f"x64_requirement_ids mismatch. Expected {expected_ids}, got {set(req_ids)}"
    
    # current_x64_reannotation_readiness must contain NO historical evidence hashes
    curr_str = str(curr)
    for h_val in hashes.values():
        assert h_val not in curr_str, f"Historical hash {h_val} found in current x64 readiness section!"


# ==========================================
# Reference-Backed Local Tests (REF1 - REF3)
# ==========================================

@pytest.mark.requires_reference
def test_REF1_arm_hash_bytes():
    data_root = os.environ.get("RAPTOR_DATA_ROOT")
    if not data_root:
        pytest.skip("RAPTOR_DATA_ROOT environment variable is not set; skipping REF1")
        
    for item in ARM_INVENTORY:
        full_path = Path(data_root) / item["path"]
        assert full_path.exists(), f"Required file not found under RAPTOR_DATA_ROOT: {item['path']}"
        
        actual_size = full_path.stat().st_size
        assert actual_size == item["bytes"], f"Byte size mismatch for {item['id']}: expected {item['bytes']}, got {actual_size}"
        
        actual_sha = compute_sha256(full_path)
        assert actual_sha == item["sha256"], f"SHA256 mismatch for {item['id']}: expected {item['sha256']}, got {actual_sha}"
        
    # Load canonical manifest and compare manifest-declared present_hashed inventory
    manifest = load_manifest()
    inventory = manifest.get("arm_inventory", {})
    present_hashed = inventory.get("present_hashed", [])
    
    assert len(present_hashed) == 14, f"Expected exactly 14 present_hashed files in manifest, got {len(present_hashed)}"
    
    # Compare each entry between manifest-declared and hardcoded expected inventory
    manifest_by_id = {entry["id"]: entry for entry in present_hashed}
    expected_by_id = {item["id"]: item for item in ARM_INVENTORY}
    
    assert set(manifest_by_id.keys()) == set(expected_by_id.keys()), "Manifest-declared arm_inventory.present_hashed IDs do not match the expected set"
    
    for item_id, expected_item in expected_by_id.items():
        manifest_item = manifest_by_id[item_id]
        assert manifest_item["path"] == expected_item["path"], f"Path mismatch for {item_id}"
        assert manifest_item["sha256"] == expected_item["sha256"], f"SHA256 mismatch for {item_id}"
        assert manifest_item["bytes"] == expected_item["bytes"], f"Bytes size mismatch for {item_id}"
        assert manifest_item["location"] == "arm", f"Location mismatch for {item_id}"
        assert manifest_item["presence"] == "present_hashed", f"Presence mismatch for {item_id}"


@pytest.mark.requires_reference
def test_REF2_return_manifest_and_provenance():
    data_root = os.environ.get("RAPTOR_DATA_ROOT")
    if not data_root:
        pytest.skip("RAPTOR_DATA_ROOT environment variable is not set; skipping REF2")
        
    vcf_path = Path(data_root) / "handoffs" / "masked-heldout-2026-07-12" / "inputs" / "holdout_input.vcf"
    prov_path = Path(data_root) / "handoffs" / "masked-heldout-2026-07-12" / "inputs" / "holdout_input.provenance.json"
    manifest_path = Path(data_root) / "handoffs" / "masked-heldout-2026-07-12" / "inputs" / "holdout_input.manifest.jsonl"
    return_manifest_path = Path(data_root) / "handoffs" / "masked-heldout-2026-07-12" / "return-post-pm1-resume" / "RETURN_MANIFEST.sha256.txt"
    
    assert vcf_path.exists()
    assert prov_path.exists()
    assert manifest_path.exists()
    assert return_manifest_path.exists()
    
    # 1. holdout_input.vcf SHA256 equals provenance.json vcf_hash equals 4dcba7c8...
    vcf_sha = compute_sha256(vcf_path)
    assert vcf_sha == "4dcba7c882b65838cedf8ce0ad56e0f7764df34b247ab412aac144d4027c622d"
    
    with open(prov_path, "r", encoding="utf-8") as f:
        prov_data = json.load(f)
        
    assert prov_data.get("vcf_hash") == vcf_sha
    
    # 2. manifest.jsonl SHA256 equals provenance.manifest_hash
    manifest_sha = compute_sha256(manifest_path)
    assert manifest_sha == "9e588cdf8ebaea2e3793e0ea74721ab5283b57c2abf045dbf3070cb6e81ec9e4"
    assert prov_data.get("manifest_hash") == manifest_sha
    
    # 3. RETURN_MANIFEST-listed hashes match the ARM copies
    with open(return_manifest_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            expected_hash = parts[0].strip().lower()
            rel_file_path = parts[1].strip()
            clean_rel_path = rel_file_path.lstrip("*").replace("./", "").replace(".\\", "")
            basename = os.path.basename(clean_rel_path)
            
            # Since keep local/reference tests ARM-present only, we assert every file exists and matches hash.
            # No silent exists() skips, and no worker-only files exist in RETURN_MANIFEST anyway.
            file_to_check = return_manifest_path.parent / basename
            assert file_to_check.exists(), f"ARM-present file listed in RETURN_MANIFEST does not exist: {file_to_check}"
            actual_hash = compute_sha256(file_to_check)
            assert actual_hash == expected_hash, f"Hash mismatch in RETURN_MANIFEST for {basename}: expected {expected_hash}, got {actual_hash}"

    # Attempt to load canonical manifest
    load_manifest()


@pytest.mark.requires_reference
def test_REF3_bias_tsv_invariants():
    data_root = os.environ.get("RAPTOR_DATA_ROOT")
    if not data_root:
        pytest.skip("RAPTOR_DATA_ROOT environment variable is not set; skipping REF3")
        
    bias_tsv_path = Path(data_root) / "handoffs" / "masked-heldout-2026-07-12" / "return-post-pm1-resume" / "holdout_input.masked.bias_output.tsv"
    assert bias_tsv_path.exists(), f"BIAS TSV not found at: {bias_tsv_path}"
    
    # Parse via BiasTsvSource with no BiasContractError
    try:
        source = BiasTsvSource(bias_tsv_path)
        records = list(source.records())
    except BiasContractError as e:
        pytest.fail(f"BiasContractError raised during BiasTsvSource parsing: {e}")
        
    # Check row count is exactly 2577
    assert len(records) == 2577, f"Expected 2577 records, got {len(records)}"
    
    # Zero duplicate identities (variant_id)
    variant_ids = [r.variant_id for r in records]
    assert len(variant_ids) == len(set(variant_ids)), "Found duplicate identities in BIAS TSV"
    
    # Attempt to load canonical manifest
    load_manifest()


# ==========================================
# Executable Local Reference Gate Command
# ==========================================

if __name__ == "__main__":
    # Local presence gate implementation
    import sys
    data_root_env = os.environ.get("RAPTOR_DATA_ROOT")
    if not data_root_env:
        print("Error: RAPTOR_DATA_ROOT environment variable is not set.", file=sys.stderr)
        sys.exit(1)
        
    missing_files = []
    print(f"Executing local reference gate under RAPTOR_DATA_ROOT: {data_root_env}")
    
    # 1. Verify the hardcoded 14 present_hashed files
    for item in ARM_INVENTORY:
        full_path = Path(data_root_env) / item["path"]
        if not full_path.exists():
            print(f"MISSING hardcoded file: {item['path']}", file=sys.stderr)
            missing_files.append(item["path"])
            continue
            
        actual_size = full_path.stat().st_size
        if actual_size != item["bytes"]:
            print(f"SIZE MISMATCH for hardcoded {item['path']}: expected {item['bytes']}, got {actual_size}", file=sys.stderr)
            missing_files.append(item["path"])
            continue
            
        actual_sha = compute_sha256(full_path)
        if actual_sha != item["sha256"]:
            print(f"HASH MISMATCH for hardcoded {item['path']}: expected {item['sha256']}, got {actual_sha}", file=sys.stderr)
            missing_files.append(item["path"])
            continue
            
        print(f"MATCHED hardcoded: {item['id']}")
        
    # 2. Once manifest exists, ALSO verify every manifest-declared present_hashed entry
    if MANIFEST_PATH.exists():
        print(f"Manifest exists. Validating manifest-declared arm_inventory.")
        try:
            with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
                manifest_data = yaml.safe_load(f)
            present_hashed_manifest = manifest_data.get("arm_inventory", {}).get("present_hashed", [])
            
            # Compare ID sets to ensure exact equality
            manifest_ids = {entry["id"] for entry in present_hashed_manifest}
            hardcoded_ids = {item["id"] for item in ARM_INVENTORY}
            if manifest_ids != hardcoded_ids:
                print(f"Error: Manifest IDs mismatch with hardcoded IDs. Manifest: {manifest_ids}, Hardcoded: {hardcoded_ids}", file=sys.stderr)
                sys.exit(2)
                
            for entry in present_hashed_manifest:
                entry_id = entry.get("id")
                entry_path = entry.get("path")
                entry_sha = entry.get("sha256")
                entry_bytes = entry.get("bytes")
                
                full_path = Path(data_root_env) / entry_path
                if not full_path.exists():
                    print(f"MISSING manifest-declared file: {entry_path}", file=sys.stderr)
                    missing_files.append(entry_path)
                    continue
                    
                actual_size = full_path.stat().st_size
                if actual_size != entry_bytes:
                    print(f"SIZE MISMATCH for manifest-declared {entry_path}: expected {entry_bytes}, got {actual_size}", file=sys.stderr)
                    missing_files.append(entry_path)
                    continue
                    
                actual_sha = compute_sha256(full_path)
                if actual_sha != entry_sha:
                    print(f"HASH MISMATCH for manifest-declared {entry_path}: expected {entry_sha}, got {actual_sha}", file=sys.stderr)
                    missing_files.append(entry_path)
                    continue
                    
                print(f"MATCHED manifest-declared: {entry_id}")
        except Exception as e:
            print(f"Error while validating manifest-declared inventory: {e}", file=sys.stderr)
            sys.exit(2)
            
    if missing_files:
        print(f"\nVerification FAILED. {len(missing_files)} files missing/mismatched.", file=sys.stderr)
        sys.stderr.flush()
        sys.exit(2)
        
    print("\nVerification SUCCESS. All files exist and match hashes/bytes perfectly.")
    sys.exit(0)
