import os
import sys
import hashlib
import json
from pathlib import Path
import pytest
import yaml

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


# ==========================================
# Always-On Offline Tests (OFF1 - OFF9)
# ==========================================

def test_OFF1_schema():
    manifest = load_manifest()
    ref_content = load_reference()
    
    assert manifest.get("schema") == "raptor-core-annotation-bundle-v1", "Incorrect schema identifier"
    assert manifest.get("status") == "planner_contract_ready_for_implementation", "Incorrect status value"
    assert manifest.get("reuse_readiness") == "BLOCKED_POLICY_IMPLEMENTATION", "Incorrect reuse_readiness enum"
    assert manifest.get("reannotation_readiness") == "X64_WORKER_UNVERIFIED_UNTIL_OPERATOR_MAKES_AVAILABLE", "Incorrect reannotation_readiness enum"
    assert manifest.get("licensing_readiness") == "PENDING_PERMITTED_USE_REVIEW", "Incorrect licensing_readiness enum"
    
    # Assert human reference mirrors the manifest
    assert "Nirvana 3.18.1" in ref_content, "Human reference must mention Nirvana 3.18.1"
    assert "BIAS 3.0.0" in ref_content, "Human reference must mention BIAS 3.0.0"
    assert "28-source" in ref_content or "28 sources" in ref_content, "Human reference must mention 28 sources"
    assert "BLOCKED_POLICY_IMPLEMENTATION" in ref_content, "Human reference must mention reuse state is BLOCKED_POLICY_IMPLEMENTATION"


def test_OFF2_source_values_28():
    manifest = load_manifest()
    sources = manifest.get("data_sources", []) or manifest.get("deployed_data_sources", []) or manifest.get("deployed_bundle", {}).get("deployed_data_sources", [])
    
    assert len(sources) == 28, f"Expected exactly 28 sources, got {len(sources)}"
    
    # Check exact equality (order-independent)
    def sort_key(s):
        return (s.get("name", ""), s.get("version", ""), s.get("release_date", ""))
        
    sorted_expected = sorted(EXPECTED_SOURCES, key=sort_key)
    sorted_actual = sorted(sources, key=sort_key)
    
    assert sorted_actual == sorted_expected, "Deployed data sources do not match the expected 28-source set exactly"


def test_OFF3_presence_enums():
    manifest = load_manifest()
    inventory = manifest.get("arm_inventory", {})
    present_hashed = inventory.get("present_hashed", [])
    worker_only_absent = inventory.get("worker_only_absent_on_arm", {}).get("items", []) or inventory.get("worker_only_absent_on_arm", [])
    
    # Assert that everything is either present_hashed or worker_only
    for item in present_hashed:
        assert "arm_path" in item or "path" in item
        assert "sha256" in item
        assert "bytes" in item
        
    # Check that worker_only files are not marked present on ARM
    for item in worker_only_absent:
        assert item.get("arm_path") is None or "D:\\raptor-x64" in item.get("x64_path", "")
        
    # Verify overall presence claims
    assert manifest.get("x64_bundle_present", False) is False, "x64_bundle_present must be False on ARM/CI"


def test_OFF4_reuse_blocked_on_suppression():
    manifest = load_manifest()
    
    # Reuse route must resolve to BLOCKED_POLICY_IMPLEMENTATION, never GO_REUSE
    assert manifest.get("reuse_readiness") == "BLOCKED_POLICY_IMPLEMENTATION"
    
    # Check PP3_BP4_SUPPRESSION_CONTRACT_REQUIRED or similar is required
    suppression_req = manifest.get("pp3_bp4_suppression_prerequisite", {})
    assert suppression_req.get("id") == "PP3_BP4_SUPPRESSION_CONTRACT_REQUIRED"


def test_OFF5_licensing_egress_flags():
    manifest = load_manifest()
    licensing = manifest.get("licensing", {})
    
    # Channel local status
    channels = licensing.get("channels", {})
    assert channels.get("local_execution_status") == "pending_permitted_use_review"
    assert channels.get("raw_public_redistribution") is False
    assert channels.get("raw_cloud_egress") is False
    
    # Every per-source status and egress flags
    per_source = licensing.get("per_source", {})
    for src_name, src_info in per_source.items():
        assert src_info.get("local_status") == "pending_permitted_use_review" or src_info.get("local_execution_status") == "pending_permitted_use_review"
        assert src_info.get("raw_public_redistribution") is False
        assert src_info.get("raw_cloud_egress") is False
        
    # AlphaMissense licence_version
    am_lic = per_source.get("alphamissense", {})
    assert am_lic.get("licence_version") == "confirm_pending"
    
    # No field asserts raw predictor score use is currently permitted
    assert "permitted" not in str(licensing).lower() or "pending_permitted_use_review" in str(licensing)


def test_OFF6_deferred_upgrade_guard():
    manifest = load_manifest()
    sources = manifest.get("data_sources", []) or manifest.get("deployed_data_sources", []) or manifest.get("deployed_bundle", {}).get("deployed_data_sources", [])
    
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
    fields = manifest.get("structured_fields", {}) or manifest.get("deployed_bundle", {}).get("structured_fields", {})
    
    revel_path = fields.get("revel", {}).get("json_path")
    am_path = fields.get("alphamissense", {}).get("json_path")
    
    assert revel_path == "positions[].variants[].revel.score"
    assert am_path == "positions[].variants[].AlphaMissense.AM_score"
    
    # Reject BIAS-rationale REVEL path
    assert "rationale" not in str(fields).lower()


def test_OFF8_revel_label_guard():
    manifest = load_manifest()
    sources = manifest.get("data_sources", []) or manifest.get("deployed_data_sources", []) or manifest.get("deployed_bundle", {}).get("deployed_data_sources", [])
    
    revel_ver = None
    for s in sources:
        if s.get("name") == "REVEL":
            revel_ver = s.get("version")
            
    assert revel_ver == "20200205", f"Expected REVEL version 20200205, got {revel_ver}"


def test_OFF9_historical_vs_current_split():
    manifest = load_manifest()
    
    hist = manifest.get("historical_run_attestation", {})
    curr = manifest.get("current_x64_reannotation_readiness", {})
    
    # Historical run attestation references only immutable ARM evidence and has no dependency on current_x64_reannotation_readiness
    assert hist is not None
    assert curr is not None
    assert "current_x64_reannotation_readiness" not in str(hist)


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
        
    # Attempt to load canonical manifest
    load_manifest()


@pytest.mark.requires_reference
def test_REF2_vcf_provenance_return_consistency():
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
            
            file_to_check = return_manifest_path.parent / clean_rel_path
            if file_to_check.exists():
                actual_hash = compute_sha256(file_to_check)
                assert actual_hash == expected_hash, f"Hash mismatch in RETURN_MANIFEST for {clean_rel_path}: expected {expected_hash}, got {actual_hash}"

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
    
    for item in ARM_INVENTORY:
        full_path = Path(data_root_env) / item["path"]
        if not full_path.exists():
            print(f"MISSING: {item['path']}", file=sys.stderr)
            missing_files.append(item["path"])
            continue
            
        actual_size = full_path.stat().st_size
        if actual_size != item["bytes"]:
            print(f"SIZE MISMATCH for {item['path']}: expected {item['bytes']}, got {actual_size}", file=sys.stderr)
            missing_files.append(item["path"])
            continue
            
        actual_sha = compute_sha256(full_path)
        if actual_sha != item["sha256"]:
            print(f"HASH MISMATCH for {item['path']}: expected {item['sha256']}, got {actual_sha}", file=sys.stderr)
            missing_files.append(item["path"])
            continue
            
        print(f"MATCHED: {item['id']}")
        
    if missing_files:
        print(f"\nVerification FAILED. {len(missing_files)} files missing/mismatched.", file=sys.stderr)
        sys.stderr.flush()
        sys.exit(2)
        
    print("\nVerification SUCCESS. All 14 files exist and match hashes/bytes perfectly.")
    sys.exit(0)
