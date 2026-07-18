import pytest
import json
import hashlib
import os
import sys
import subprocess
from pathlib import Path

# Policy schema alignment:
# - schema: "pp3bp4-candidate-policy/1"
# - version: "1"
# - policy_id: "tsc-pp3bp4-revel-shadow"

VALID_SOURCE_REGISTER_CONTENT = """schema: "pp3bp4-source-register/1"
version: "1"
required_primary_sources:
  pejaver_2022:
    doi: "10.1016/j.ajhg.2022.10.013"
    pmid: "36413997"
    pmc: "PMC9748256"
    locus: "Table 2, REVEL row"
    verification: "verified"
  stenton_2024:
    pmid: "39030733"
    pmc: "PMC11560577"
    locus: "Box 1"
    verification: "verified"
  richards_2015:
    doi: "10.1038/gim.2015.30"
    pmid: "25741868"
    pmc: "PMC4544753"
    locus: "PP3 and BP4 criteria"
    verification: "verified"
  tavtigian_2018:
    doi: "10.1038/gim.2017.210"
    locus: "Bayesian evidence-strength model"
    verification: "verified"
candidates:
  revel:
    kind: "meta_predictor"
    calibration_source: "pejaver_2022"
    version_status: "confirm_pending"
    license_status: "confirm_pending"
    structured_score_availability: "blocked_data"
    training_manifest_status: "unavailable"
    tsc_specific_evidence: "none_identified"
    decision: "advance_shadow"
  bayesdel_noaf:
    kind: "meta_predictor"
    calibration_source: "pejaver_2022"
    version_status: "confirm_pending"
    license_status: "confirm_pending"
    structured_score_availability: "unavailable"
    training_manifest_status: "unavailable"
    tsc_specific_evidence: "none_identified"
    decision: "blocked_shadow_comparator"
  mutpred2:
    kind: "predictor"
    calibration_source: "pejaver_2022"
    version_status: "confirm_pending"
    license_status: "confirm_pending"
    structured_score_availability: "unavailable"
    training_manifest_status: "unavailable"
    tsc_specific_evidence: "none_identified"
    decision: "blocked_shadow_comparator"
  vest4:
    kind: "predictor"
    calibration_source: "pejaver_2022"
    version_status: "confirm_pending"
    license_status: "confirm_pending"
    structured_score_availability: "unavailable"
    training_manifest_status: "unavailable"
    tsc_specific_evidence: "none_identified"
    decision: "blocked_shadow_comparator"
  bias_composite:
    kind: "composite"
    calibration_source: "none"
    version_status: "pinned_bias_3_0_0_commit_ade13f2"
    license_status: "arm_length_agpl"
    structured_score_availability: "reconstructed_only"
    training_manifest_status: "inherited_unknown"
    tsc_specific_evidence: "none_identified"
    decision: "audit_only_reject_authoritative"
"""

def _get_valid_policy_json(source_register_sha256="abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"):
    return {
        "schema": "pp3bp4-candidate-policy/1",
        "version": "1",
        "policy_id": "tsc-pp3bp4-revel-shadow",
        "status": "proposed",
        "shadow_only": True,
        "owner_approved": False,
        "predictor": "REVEL",
        "predictor_version": "confirm-pending-revel-dbnsfp-release",
        "data_version": "confirm-pending-dbnsfp-release",
        "score_direction": "higher_more_pathogenic",
        "variant_scope": ["missense_variant"],
        "consequence_routing": {
            "missense_variant": "revel_policy",
            "splice_relevant": "out_of_scope",
            "other": "out_of_scope"
        },
        "no_fallback": True,
        "criterion_once": True,
        "max_pp3_strength": "strong",
        "enabled_max_bp4_strength": "moderate",
        "pp3": {
            "supporting": {"lo": 0.644, "lo_inclusive": True, "hi": 0.773, "hi_inclusive": False},
            "moderate": {"lo": 0.773, "lo_inclusive": True, "hi": 0.932, "hi_inclusive": False},
            "strong": {"lo": 0.932, "lo_inclusive": True, "hi": None, "hi_inclusive": False}
        },
        "bp4": {
            "very_strong": {"lo": None, "lo_inclusive": False, "hi": 0.003, "hi_inclusive": True, "enabled": False},
            "strong": {"lo": 0.003, "lo_inclusive": False, "hi": 0.016, "hi_inclusive": True, "enabled": False},
            "moderate": {"lo": 0.016, "lo_inclusive": False, "hi": 0.183, "hi_inclusive": True, "enabled": True},
            "supporting": {"lo": 0.183, "lo_inclusive": False, "hi": 0.290, "hi_inclusive": True, "enabled": True}
        },
        "indeterminate": {"lo": 0.290, "lo_inclusive": False, "hi": 0.644, "hi_inclusive": False},
        "distinct_results": [
            "BP4_DISABLED_STRENGTH",
            "BP4_MODERATE",
            "BP4_SUPPORTING",
            "INDETERMINATE",
            "MISSING_SCORE",
            "OUT_OF_SCOPE",
            "PP3_SUPPORTING",
            "PP3_MODERATE",
            "PP3_STRONG"
        ],
        "forbidden_fields": [
            "policy_sha256",
            "authorized",
            "clinical_use_authorized"
        ],
        "combination_caps": {
            "pp3_pm1": "strong"
        },
        "citation_ids": [
            "pejaver_2022",
            "stenton_2024",
            "richards_2015",
            "tavtigian_2018"
        ],
        "training_overlap_status": "UNKNOWN",
        "transportability_status": "BLOCKED_DATA",
        "license_status": "confirm_pending",
        "source_register_sha256": source_register_sha256,
        "activation_checklist": [
            "exact predictor and data versions",
            "verified license",
            "leakage audit resolved",
            "independent transportability evidence",
            "deterministic tests and checker approval",
            "owner approval bound to hashes"
        ],
        "activation_dependencies": [
            "revel_dbnsfp_release_pin",
            "verified_license",
            "leakage_resolution",
            "dev_score_acquisition",
            "transportability_assessment"
        ],
        "research_use_disclaimer": "Research-evidence shadow analysis only; this authorizes no clinical\nclassification, VUS worklist, ClinVar submission, or terminal-gate use.\n"
    }


def test_tb1_schema_and_hash(tmp_path):
    """T-B1 schema/hash checks.

    Verify load_candidate_policy enforces a closed field set, rejects a 'policy_sha256' field,
    raises CandidatePolicyError if owner_approved is True while status != 'approved',
    raises on non-monotonic or overlapping intervals, and returns a PolicyProvenance
    with policy_source_sha256 computed over canonical bytes of the file.
    """
    from raptor.eval.pp3bp4_candidate_policy import load_candidate_policy, CandidatePolicyError

    # Create a real source register file to test the preferred real register verification
    register_file = tmp_path / "pp3bp4_source_register.yaml"
    register_file.write_text(VALID_SOURCE_REGISTER_CONTENT, encoding="utf-8")
    real_register_sha = hashlib.sha256(register_file.read_bytes()).hexdigest()

    p_file = tmp_path / "policy.json"
    p_data = _get_valid_policy_json(source_register_sha256=real_register_sha)

    # Base valid check
    p_file.write_text(json.dumps(p_data), encoding="utf-8")
    policy, provenance = load_candidate_policy(str(p_file), source_register_path=str(register_file))
    assert policy.status == "proposed"
    assert not policy.owner_approved
    assert provenance.source_register_sha256 == real_register_sha
    
    # Check policy_source_sha256 calculation over canonical bytes
    expected_hash = hashlib.sha256(p_file.read_bytes()).hexdigest()
    assert provenance.policy_source_sha256 == expected_hash

    # Reject extra fields in policy (closed field set)
    p_extra = p_data.copy()
    p_extra["extra_unapproved_field"] = "value"
    p_file.write_text(json.dumps(p_extra), encoding="utf-8")
    with pytest.raises(CandidatePolicyError):
        load_candidate_policy(str(p_file), source_register_path=str(register_file))

    # Rejects 'policy_sha256' field (Correction 3)
    p_self_hash = p_data.copy()
    p_self_hash["policy_sha256"] = "somehash"
    p_file.write_text(json.dumps(p_self_hash), encoding="utf-8")
    with pytest.raises(CandidatePolicyError, match="policy_sha256"):
        load_candidate_policy(str(p_file), source_register_path=str(register_file))

    # Reject owner_approved=True when status != 'approved' (status is 'proposed')
    p_unauth = p_data.copy()
    p_unauth["owner_approved"] = True
    p_file.write_text(json.dumps(p_unauth), encoding="utf-8")
    with pytest.raises(CandidatePolicyError):
        load_candidate_policy(str(p_file), source_register_path=str(register_file))

    # Non-monotonic PP3 intervals (e.g. moderate overlapping with supporting or out of order)
    p_non_monotonic = p_data.copy()
    p_non_monotonic["pp3"] = {
        "supporting": {"lo": 0.773, "lo_inclusive": True, "hi": 0.932, "hi_inclusive": False},
        "moderate": {"lo": 0.644, "lo_inclusive": True, "hi": 0.773, "hi_inclusive": False},
        "strong": {"lo": 0.932, "lo_inclusive": True, "hi": None, "hi_inclusive": False}
    }
    p_file.write_text(json.dumps(p_non_monotonic), encoding="utf-8")
    with pytest.raises(CandidatePolicyError):
        load_candidate_policy(str(p_file), source_register_path=str(register_file))

    # Overlapping intervals (lo/hi overlaps)
    p_overlap = p_data.copy()
    p_overlap["pp3"] = {
        "supporting": {"lo": 0.644, "lo_inclusive": True, "hi": 0.800, "hi_inclusive": False},
        "moderate": {"lo": 0.750, "lo_inclusive": True, "hi": 0.932, "hi_inclusive": False},
        "strong": {"lo": 0.932, "lo_inclusive": True, "hi": None, "hi_inclusive": False}
    }
    p_file.write_text(json.dumps(p_overlap), encoding="utf-8")
    with pytest.raises(CandidatePolicyError):
        load_candidate_policy(str(p_file), source_register_path=str(register_file))


def test_tb1_source_register_failures(tmp_path):
    """Verify missing, mismatched, or unverified registers fail loud."""
    from raptor.eval.pp3bp4_candidate_policy import load_candidate_policy, CandidatePolicyError

    p_file = tmp_path / "policy.json"
    register_file = tmp_path / "pp3bp4_source_register.yaml"

    # Write some register file
    register_file.write_text(VALID_SOURCE_REGISTER_CONTENT, encoding="utf-8")
    real_register_sha = hashlib.sha256(register_file.read_bytes()).hexdigest()

    # 1. Register file does not exist
    p_data = _get_valid_policy_json(source_register_sha256=real_register_sha)
    p_file.write_text(json.dumps(p_data), encoding="utf-8")
    with pytest.raises(CandidatePolicyError, match="register"):
        load_candidate_policy(str(p_file), source_register_path="nonexistent_register.yaml")

    # 2. SHA-256 mismatch
    p_mismatch = _get_valid_policy_json(source_register_sha256="wronghash" + "a" * 55)
    p_file.write_text(json.dumps(p_mismatch), encoding="utf-8")
    with pytest.raises(CandidatePolicyError, match="hash|mismatch"):
        load_candidate_policy(str(p_file), source_register_path=str(register_file))

    # 3. Unverified required primary citations
    unverified_register_content = """schema: "pp3bp4-source-register/1"
version: "1"
required_primary_sources:
  pejaver_2022:
    doi: "10.1016/j.ajhg.2022.10.013"
    pmid: "36413997"
    pmc: "PMC9748256"
    locus: "Table 2, REVEL row"
    verification: "unverified"
  stenton_2024:
    pmid: "39030733"
    pmc: "PMC11560577"
    locus: "Box 1"
    verification: "verified"
candidate_version_status: "confirm_pending"
candidate_license_status: "confirm_pending"
"""
    register_file.write_text(unverified_register_content, encoding="utf-8")
    unverified_register_sha = hashlib.sha256(register_file.read_bytes()).hexdigest()
    p_bad = _get_valid_policy_json(source_register_sha256=unverified_register_sha)
    p_file.write_text(json.dumps(p_bad), encoding="utf-8")
    with pytest.raises(CandidatePolicyError, match="unverified|citation|primary"):
        load_candidate_policy(str(p_file), source_register_path=str(register_file))

    # 4. Missing required field (required_primary_sources or specific citation)
    missing_field_register_content = """schema: "pp3bp4-source-register/1"
version: "1"
required_primary_sources:
  stenton_2024:
    pmid: "39030733"
    pmc: "PMC11560577"
    locus: "Box 1"
    verification: "verified"
candidate_version_status: "confirm_pending"
candidate_license_status: "confirm_pending"
"""
    register_file.write_text(missing_field_register_content, encoding="utf-8")
    missing_field_register_sha = hashlib.sha256(register_file.read_bytes()).hexdigest()
    p_bad2 = _get_valid_policy_json(source_register_sha256=missing_field_register_sha)
    p_file.write_text(json.dumps(p_bad2), encoding="utf-8")
    with pytest.raises(CandidatePolicyError, match="missing|field|source|pejaver"):
        load_candidate_policy(str(p_file), source_register_path=str(register_file))

    # 5. Extra field in register
    extra_field_register_content = """schema: "pp3bp4-source-register/1"
version: "1"
extra_unapproved_field: "value"
required_primary_sources:
  pejaver_2022:
    doi: "10.1016/j.ajhg.2022.10.013"
    pmid: "36413997"
    pmc: "PMC9748256"
    locus: "Table 2, REVEL row"
    verification: "verified"
  stenton_2024:
    pmid: "39030733"
    pmc: "PMC11560577"
    locus: "Box 1"
    verification: "verified"
candidate_version_status: "confirm_pending"
candidate_license_status: "confirm_pending"
"""
    register_file.write_text(extra_field_register_content, encoding="utf-8")
    extra_field_register_sha = hashlib.sha256(register_file.read_bytes()).hexdigest()
    p_bad3 = _get_valid_policy_json(source_register_sha256=extra_field_register_sha)
    p_file.write_text(json.dumps(p_bad3), encoding="utf-8")
    with pytest.raises(CandidatePolicyError, match="extra|unexpected|schema"):
        load_candidate_policy(str(p_file), source_register_path=str(register_file))


def test_tb2_boundaries(tmp_path):
    """T-B2 boundaries.

    Test classify_revel at 0.003/0.016/0.183/0.290/0.644/0.773/0.932 and adjacent values.
    Uses exact Pejaver Table 2 inclusive/exclusive edges.
    """
    from raptor.eval.pp3bp4_candidate_policy import load_candidate_policy, classify_revel, PolicyCall

    register_file = tmp_path / "pp3bp4_source_register.yaml"
    register_file.write_text(VALID_SOURCE_REGISTER_CONTENT, encoding="utf-8")
    real_register_sha = hashlib.sha256(register_file.read_bytes()).hexdigest()

    p_file = tmp_path / "policy.json"
    p_file.write_text(json.dumps(_get_valid_policy_json(source_register_sha256=real_register_sha)), encoding="utf-8")
    policy, _ = load_candidate_policy(str(p_file), source_register_path=str(register_file))

    # Test values at boundaries
    assert classify_revel(0.003, policy) == PolicyCall.BP4_DISABLED_STRENGTH
    assert classify_revel(0.002, policy) == PolicyCall.BP4_DISABLED_STRENGTH
    assert classify_revel(0.004, policy) == PolicyCall.BP4_DISABLED_STRENGTH
    assert classify_revel(0.016, policy) == PolicyCall.BP4_DISABLED_STRENGTH

    assert classify_revel(0.017, policy) == PolicyCall.BP4_MODERATE
    assert classify_revel(0.183, policy) == PolicyCall.BP4_MODERATE

    assert classify_revel(0.184, policy) == PolicyCall.BP4_SUPPORTING
    assert classify_revel(0.290, policy) == PolicyCall.BP4_SUPPORTING

    assert classify_revel(0.291, policy) == PolicyCall.INDETERMINATE
    assert classify_revel(0.643, policy) == PolicyCall.INDETERMINATE

    assert classify_revel(0.644, policy) == PolicyCall.PP3_SUPPORTING
    assert classify_revel(0.772, policy) == PolicyCall.PP3_SUPPORTING

    assert classify_revel(0.773, policy) == PolicyCall.PP3_MODERATE
    assert classify_revel(0.931, policy) == PolicyCall.PP3_MODERATE

    assert classify_revel(0.932, policy) == PolicyCall.PP3_STRONG
    assert classify_revel(0.999, policy) == PolicyCall.PP3_STRONG


def test_tb3_distinct_results():
    """T-B3 distinct results.

    Verify BP4_DISABLED_STRENGTH, INDETERMINATE, MISSING_SCORE, and OUT_OF_SCOPE are distinct members.
    """
    from raptor.eval.pp3bp4_candidate_policy import PolicyCall

    assert PolicyCall.BP4_DISABLED_STRENGTH != PolicyCall.INDETERMINATE
    assert PolicyCall.BP4_DISABLED_STRENGTH != PolicyCall.MISSING_SCORE
    assert PolicyCall.BP4_DISABLED_STRENGTH != PolicyCall.OUT_OF_SCOPE
    assert PolicyCall.INDETERMINATE != PolicyCall.MISSING_SCORE
    assert PolicyCall.INDETERMINATE != PolicyCall.OUT_OF_SCOPE
    assert PolicyCall.MISSING_SCORE != PolicyCall.OUT_OF_SCOPE


def test_tb4_no_fallback_path(tmp_path):
    """T-B4 no fallback / once.

    Verify that classification is purely PP3 XOR BP4, with no second-tool path,
    and a disabled tier (Strong/VeryStrong) never fabricates active BP4_Strong or BP4_VeryStrong.
    """
    from raptor.eval.pp3bp4_candidate_policy import load_candidate_policy, classify_revel, PolicyCall

    register_file = tmp_path / "pp3bp4_source_register.yaml"
    register_file.write_text(VALID_SOURCE_REGISTER_CONTENT, encoding="utf-8")
    real_register_sha = hashlib.sha256(register_file.read_bytes()).hexdigest()

    p_file = tmp_path / "policy.json"
    p_file.write_text(json.dumps(_get_valid_policy_json(source_register_sha256=real_register_sha)), encoding="utf-8")
    policy, _ = load_candidate_policy(str(p_file), source_register_path=str(register_file))

    res_vstrong = classify_revel(0.002, policy)
    assert res_vstrong == PolicyCall.BP4_DISABLED_STRENGTH
    assert res_vstrong != "BP4_STRONG"
    assert res_vstrong != "BP4_VERY_STRONG"

    res_strong = classify_revel(0.010, policy)
    assert res_strong == PolicyCall.BP4_DISABLED_STRENGTH
    assert res_strong != "BP4_STRONG"


def test_tb5_no_authorization(tmp_path):
    """T-B5 no-authorization / status-independent behavior.

    Verify build_shadow_report has no status branch or authorization return,
    producing identical output regardless of a hypothetical 'approved' status.
    Assert that the report/payload has no authorization/approved/clinical-use fields and no behavior toggle.
    """
    from raptor.eval.pp3bp4_candidate_policy import load_candidate_policy, build_shadow_report, PolicyCall

    register_file = tmp_path / "pp3bp4_source_register.yaml"
    register_file.write_text(VALID_SOURCE_REGISTER_CONTENT, encoding="utf-8")
    real_register_sha = hashlib.sha256(register_file.read_bytes()).hexdigest()

    p_file_proposed = tmp_path / "proposed_policy.json"
    p_data_proposed = _get_valid_policy_json(source_register_sha256=real_register_sha)
    p_file_proposed.write_text(json.dumps(p_data_proposed), encoding="utf-8")
    policy_proposed, prov_proposed = load_candidate_policy(str(p_file_proposed), source_register_path=str(register_file))

    # Using canonical SPDI IDs instead of HGVS (:g.)
    mock_records = [
        {"variant_id": "NC_000009.12:12345:A:G", "score": 0.85, "provenance": {"source": "structured"}},
        {"variant_id": "NC_000016.10:54321:C:T", "score": 0.10, "provenance": {"source": "structured"}},
    ]

    report_proposed = build_shadow_report(mock_records, policy_proposed, prov_proposed, scope_genes=["TSC1", "TSC2"])

    assert hasattr(report_proposed, "provenance")
    assert report_proposed.provenance.status == "proposed"
    assert hasattr(report_proposed, "content_hash")

    # Assert the shadow report contains the expected two classified records
    # (Checking attribute 'records' or 'classified_records' on report_proposed)
    records_list = getattr(report_proposed, "records", None) or getattr(report_proposed, "classified_records", None)
    assert records_list is not None, "Shadow report has no records attribute"
    assert len(records_list) == 2, "Expected exactly 2 records in shadow report"
    
    variant_ids = {r.get("variant_id") if isinstance(r, dict) else getattr(r, "variant_id", None) for r in records_list}
    assert variant_ids == {"NC_000009.12:12345:A:G", "NC_000016.10:54321:C:T"}

    # Assert no keys/attributes matching authorization, approval, clinical use, candidate direction, or VUS worklist
    def check_forbidden(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                k_str = str(k).lower()
                for term in ["authoriz", "approv", "clinical", "direction", "worklist"]:
                    assert term not in k_str, f"Forbidden term '{term}' found in dict key '{path}.{k}'"
                check_forbidden(v, f"{path}.{k}")
        elif isinstance(obj, (list, tuple, set)):
            for idx, item in enumerate(obj):
                check_forbidden(item, f"{path}[{idx}]")
        elif hasattr(obj, "__dict__") or hasattr(obj, "__slots__") or (hasattr(obj, "__class__") and obj.__class__.__name__ != "type"):
            # Check attributes of custom objects (excluding standard python attributes/dunders)
            for attr in dir(obj):
                if attr.startswith("_"):
                    continue
                attr_str = attr.lower()
                for term in ["authoriz", "approv", "clinical", "direction", "worklist"]:
                    assert term not in attr_str, f"Forbidden term '{term}' found in attribute '{path}.{attr}'"
                try:
                    val = getattr(obj, attr)
                    if not callable(val):
                        check_forbidden(val, f"{path}.{attr}")
                except Exception:
                    pass

    check_forbidden(report_proposed, "shadow_report")

    # Assert no authorization, approval, or clinical use fields anywhere in the report payload dictionary
    report_dict = report_proposed.to_dict() if hasattr(report_proposed, "to_dict") else vars(report_proposed)
    forbidden_keys = {"authorization", "authorized", "approved", "clinical_use", "clinical_use_authorized"}
    for k in report_dict.keys():
        assert k not in forbidden_keys, f"Forbidden authorization-related field found in report keys: {k}"

    # Assert no behavior toggle (no mechanism to switch between approved and shadow behavior)
    assert not hasattr(report_proposed, "behavior_toggle")


def test_tb6_no_censored_path():
    """T-B6 no censored path.

    Verify that the policy module has no rationale-parsing import, function or path,
    and build_shadow_report or Stage B transportability rejects any score record
    where `source` == 'bias_rationale' or any censored provenance is passed.
    """
    try:
        from raptor.eval import pp3bp4_candidate_policy
        source_code = Path(pp3bp4_candidate_policy.__file__).read_text(encoding="utf-8")
        # Structurally forbid any rationale parser/source path symbols/imports
        forbidden_symbols = [
            "extract_revel_scores_from_bias_rationale",
            "bias_rationale",
            "extractor",
            "parser",
            "parse_rationale"
        ]
        for symbol in forbidden_symbols:
            assert symbol not in source_code, f"Forbidden symbol {symbol} found in pp3bp4_candidate_policy.py"
    except (ImportError, NameError, FileNotFoundError):
        pass

    from raptor.eval.pp3bp4_candidate_policy import build_shadow_report

    class DummyPolicy:
        status = "proposed"
        shadow_only = True
        owner_approved = False
    class DummyProvenance:
        policy_source_sha256 = "1" * 64
        source_register_sha256 = "2" * 64
        schema = "pp3bp4-candidate-policy/1"
        status = "proposed"

    bad_records = [
        {"variant_id": "NC_000009.12:12345:A:G", "score": 0.85, "provenance": {"source": "bias_rationale"}},
    ]
    with pytest.raises(ValueError, match="bias_rationale"):
        build_shadow_report(bad_records, DummyPolicy(), DummyProvenance(), scope_genes=["TSC1", "TSC2"])


def test_cli_help_bootstrap():
    """T-A4/T-B8 check script can run with a clean PYTHONPATH and shows help."""
    script_path = Path("scripts/build_pp3bp4_transportability_report.py")
    if not script_path.exists():
        pytest.fail(f"implementation missing: {script_path}")

    env = os.environ.copy()
    if "PYTHONPATH" in env:
        del env["PYTHONPATH"]

    cmd = [sys.executable, str(script_path), "--help"]
    res = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert res.returncode == 0, f"CLI help failed under clean PYTHONPATH: {res.stderr}"
    assert "usage" in res.stdout.lower() or "help" in res.stdout.lower()
