import pytest
import json
import subprocess
import sys
import hashlib
from pathlib import Path

# All imports from raptor are done inside the test functions
# to ensure the test suite collects cleanly under pytest even
# when implementation elements are absent.

def test_g_dm1_v2_loader_validation(tmp_path):
    """
    G-DM1: v2 loader accepts the exact closed v2 field set and populates
    PredictorPolicy properties; rejects unknown/extra fields, missing required fields,
    unknown mode values, and non-64-hex hashes.
    """
    try:
        from raptor.eval.predictor_policy import load_predictor_policy, PredictorPolicyError
    except ImportError:
        pytest.fail("Missing predictor_policy implementation")

    valid_v2 = {
        "schema": "bp4pp3-predictor-policy/2",
        "status": "approved",
        "mode": "disabled_manual",
        "predictor_source_hash": "a" * 64,
        "correction_hash": "b" * 64,
        "production_config_hash": "c" * 64,
        "eval_config_hash": "d" * 64,
        "lineage_policy_hash": "e" * 64,
        "runtime_bundle_hash": "f" * 64,
        "decision_reference": "ADR-0012"
    }

    def write_policy(name, data):
        p = tmp_path / name
        p.write_text(json.dumps(data))
        return str(p)

    # 1. Accept valid v2
    policy = load_predictor_policy(write_policy("valid_v2.json", valid_v2))
    assert policy.schema == "bp4pp3-predictor-policy/2"
    assert policy.status == "approved"
    assert policy.mode == "disabled_manual"
    assert policy.predictor_source_hash == "a" * 64
    assert policy.correction_hash == "b" * 64
    assert policy.production_config_hash == "c" * 64
    assert policy.eval_config_hash == "d" * 64
    assert policy.lineage_policy_hash == "e" * 64
    assert policy.runtime_bundle_hash == "f" * 64
    assert policy.decision_reference == "ADR-0012"
    assert policy.approved is True

    # 2. Reject unknown/extra fields
    extra_field = valid_v2.copy()
    extra_field["unknown_field"] = "value"
    with pytest.raises(PredictorPolicyError, match="unknown field"):
        load_predictor_policy(write_policy("extra.json", extra_field))

    # 3. Reject missing required v2 fields
    for field in ("mode", "lineage_policy_hash", "runtime_bundle_hash"):
        missing_field = valid_v2.copy()
        del missing_field[field]
        with pytest.raises(PredictorPolicyError, match="missing required field"):
            load_predictor_policy(write_policy(f"missing_{field}.json", missing_field))

    # 4. Reject unknown mode values
    bad_mode = valid_v2.copy()
    bad_mode["mode"] = "active_enforced"
    with pytest.raises(PredictorPolicyError, match="unknown mode"):
        load_predictor_policy(write_policy("bad_mode.json", bad_mode))

    # 5. Reject non-64-hex config/lineage hashes
    for field in ("production_config_hash", "eval_config_hash", "lineage_policy_hash"):
        bad_hash = valid_v2.copy()
        bad_hash[field] = "not-64-hex"
        with pytest.raises(PredictorPolicyError, match="64-hex|hash|sha256"):
            load_predictor_policy(write_policy(f"bad_{field}.json", bad_hash))


def test_g_dm2_verify_disabled_config_hashes(tmp_path):
    """
    G-DM2: verify_disabled_config_hashes hashes the ACTUAL given config paths
    and passes when all match, raising PredictorPolicyError on mismatch or missing file.
    """
    try:
        from raptor.eval.predictor_policy import (
            load_predictor_policy,
            verify_disabled_config_hashes,
            PredictorPolicyError,
        )
    except ImportError:
        pytest.fail("Missing predictor_policy implementation")

    scorer_bytes = b"production scorer configuration bytes"
    eval_bytes = b"evaluation metrics configuration bytes"
    lineage_bytes = b"bias lineage configuration bytes"

    scorer_file = tmp_path / "tsc.yaml"
    eval_file = tmp_path / "tsc2.yaml"
    lineage_file = tmp_path / "bias_lineage.yaml"

    scorer_file.write_bytes(scorer_bytes)
    eval_file.write_bytes(eval_bytes)
    lineage_file.write_bytes(lineage_bytes)

    scorer_hash = hashlib.sha256(scorer_bytes).hexdigest()
    eval_hash = hashlib.sha256(eval_bytes).hexdigest()
    lineage_hash = hashlib.sha256(lineage_bytes).hexdigest()

    policy_data = {
        "schema": "bp4pp3-predictor-policy/2",
        "status": "approved",
        "mode": "disabled_manual",
        "predictor_source_hash": "a" * 64,
        "correction_hash": "b" * 64,
        "production_config_hash": scorer_hash,
        "eval_config_hash": eval_hash,
        "lineage_policy_hash": lineage_hash,
        "runtime_bundle_hash": "c" * 64,
        "decision_reference": "ADR-0012"
    }

    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy_data))
    policy = load_predictor_policy(policy_path)

    # Passes when all three match
    verify_disabled_config_hashes(policy, scorer_file, eval_file, lineage_file)

    # Raises on any mismatch
    for bad_file, content in (
        (scorer_file, b"mismatched scorer"),
        (eval_file, b"mismatched eval"),
        (lineage_file, b"mismatched lineage"),
    ):
        original_bytes = bad_file.read_bytes()
        bad_file.write_bytes(content)
        with pytest.raises(PredictorPolicyError, match="mismatch|hash"):
            verify_disabled_config_hashes(policy, scorer_file, eval_file, lineage_file)
        bad_file.write_bytes(original_bytes)  # restore

    # Raises on missing file
    missing_file = tmp_path / "missing.yaml"
    with pytest.raises(PredictorPolicyError, match="not found|missing"):
        verify_disabled_config_hashes(policy, missing_file, eval_file, lineage_file)


def test_g_dm3_policy_disabled_evidence_source():
    """
    G-DM3: PolicyDisabledEvidenceSource strips PP3 and BP4, passes other calls unchanged,
    reports exact suppressed counts, and is idempotent across repeated get_evidence calls.
    """
    try:
        from raptor.eval.terminal_source import PolicyDisabledEvidenceSource
    except ImportError:
        pytest.fail("Missing terminal_source implementation")

    class DummySource:
        def __init__(self, evidence_map):
            self.evidence_map = evidence_map
            self.variant_ids = tuple(evidence_map.keys())
        def get_evidence(self, variant_id):
            return self.evidence_map[variant_id]

    raw_evidence = {
        "var_1": (
            ("PVS1", "very_strong", "pathogenic"),
            ("PP3", "moderate", "pathogenic"),
            ("BP4", "supporting", "benign"),
            ("PM2", "supporting", "pathogenic")
        ),
        "var_2": (
            ("BP4", "supporting", "benign"),
        )
    }

    wrapped = PolicyDisabledEvidenceSource(DummySource(raw_evidence))

    # Test stripping of PP3 and BP4, retaining others
    assert wrapped.get_evidence("var_1") == (
        ("PVS1", "very_strong", "pathogenic"),
        ("PM2", "supporting", "pathogenic"),
    )

    # Verify suppressed counts are tracked properly
    assert wrapped.suppressed_counts == {"PP3": 1, "BP4": 1}

    # Test idempotence: calling again for same variant doesn't double-count
    assert wrapped.get_evidence("var_1") == (
        ("PVS1", "very_strong", "pathogenic"),
        ("PM2", "supporting", "pathogenic"),
    )
    assert wrapped.suppressed_counts == {"PP3": 1, "BP4": 1}

    # Process another variant containing BP4
    assert wrapped.get_evidence("var_2") == ()
    assert wrapped.suppressed_counts == {"PP3": 1, "BP4": 2}


def _write_manifest_line(data):
    return json.dumps(data) + "\n"


def _create_mock_holdout_package(tmp_path):
    """
    Helper to setup realistic control/manifest/evidence structure for subprocess tests.
    """
    ref_root = tmp_path / "reference-root"
    ref_root.mkdir()
    
    # 1. Scorer, eval, and lineage config files
    scorer_bytes = Path("configs/acmg/tsc.yaml").read_bytes()
    eval_bytes = Path("configs/eval/tsc2.yaml").read_bytes()
    lineage_bytes = Path("configs/eval/bias_lineage.yaml").read_bytes()

    scorer_file = tmp_path / "tsc.yaml"
    eval_file = tmp_path / "tsc2.yaml"
    lineage_file = tmp_path / "bias_lineage.yaml"

    scorer_file.write_bytes(scorer_bytes)
    eval_file.write_bytes(eval_bytes)
    lineage_file.write_bytes(lineage_bytes)

    scorer_hash = hashlib.sha256(scorer_bytes).hexdigest()
    eval_hash = hashlib.sha256(eval_bytes).hexdigest()
    lineage_hash = hashlib.sha256(lineage_bytes).hexdigest()

    # 2. Control files
    status_file = tmp_path / "TERMINAL_STATUS.txt"
    status_file.write_text("SCORED_MASKED\n", encoding="utf-8")
    skip_file = tmp_path / "evaluation_skip_list.txt"
    skip_file.write_text("\n", encoding="utf-8")

    # 3. TSV bias output with PP3 & BP4 firings
    bias_tsv = tmp_path / "bias_output_slice.tsv"
    # Mini slice containing PP3 & BP4
    bias_header = "chromosome\tposition\trefAllele\taltAllele\tvariantType\tconsequence\tacmgClassification\talleleFreq\thgvsg\thgvsc\thgvsp\taaChange\tgeneName\tpubmedIds\tassociatedDiseases\tdbSnpids\ttranscript\trationale\n"
    bias_row = 'chr2\t26684723\tG\tA\tSNV\tmissense_variant\tpathogenic\t\tNC_000002.11:g.26684723G>A\tNM_194248.2:c.5374C>T\tNP_919224.1:p.(Arg1792Cys)\tR1792C\tOTOF\t28492532\tautosomal recessive nonsyndromic hearing loss 9\trs142111099\tNM_194248.2\t{"pvs": {"pvs1": [0, ""]}, "ps": {"ps1": [0, ""], "ps2": [0, ""], "ps3": [0, ""], "ps4": [0, ""]}, "pm": {"pm1": [0, ""], "pm2": [0, ""], "pm3": [0, ""], "pm4": [0, ""], "pm5": [0, ""], "pm6": [0, ""]}, "pp": {"pp1": [0, ""], "pp2": [0, ""], "pp3": [3, "PP3_strong: 2 line(s); strong revel 0.8 | strong AlphaMissense 0.9"], "pp4": [0, ""], "pp5": [0, ""]}, "ba": {"ba1": [0, ""]}, "bs": {"bs1": [0, ""], "bs2": [0, ""], "bs3": [0, ""], "bs4": [0, ""]}, "bp": {"bp1": [0, ""], "bp2": [0, ""], "bp3": [0, ""], "bp4": [1, "BP4_supporting: supporting REVEL 0.1"], "bp5": [0, ""], "bp6": [0, ""], "bp7": [0, ""]}}\n'
    bias_tsv.write_text(bias_header + bias_row, encoding="utf-8")

    # 4. Holdout manifest
    manifest_file = tmp_path / "holdout_manifest.json"
    manifest_file.write_text('{"variant_id": "chr2:g.26684723G>A"}\n', encoding="utf-8")

    # 5. Benchmark files
    benchmark_file = tmp_path / "benchmark.json"
    benchmark_file.write_text('{"variant_id": "chr2:g.26684723G>A", "label": "P"}\n', encoding="utf-8")

    # 6. Mask ledgers matching holdout count conservation
    mask_ledger = tmp_path / "mask_ledger.json"
    mask_ledger.write_text(json.dumps({
        "input_records": 10,
        "output_records": 9,
        "matched_records_removed": 1,
        "matched_holdout_identities": ["chr2:g.26684723G>A"],
        "holdout_identities_not_present": []
    }), encoding="utf-8")

    remask_audit = tmp_path / "remask_audit.json"
    remask_audit.write_text(json.dumps({
        "input_records": 9,
        "output_records": 9,
        "matched_records_removed": 0,
        "matched_holdout_identities": [],
        "holdout_identities_not_present": ["chr2:g.26684723G>A"]
    }), encoding="utf-8")

    # 7. Return manifest binding hashes
    return_manifest = tmp_path / "return_manifest.txt"
    with open(return_manifest, "w", encoding="utf-8") as f:
        for f_item in (status_file, skip_file, bias_tsv, mask_ledger, remask_audit):
            digest = hashlib.sha256(f_item.read_bytes()).hexdigest()
            f.write(f"{digest} *{f_item.name}\n")

    # 8. Compute bundle hash over actual runtime verifier components
    # We will simulate mock enforcement files
    f_policy = tmp_path / "predictor_policy.py"
    f_source = tmp_path / "terminal_source.py"
    f_runner = tmp_path / "run_masked_holdout_eval.py"
    f_policy.write_text("dummy policy content", encoding="utf-8")
    f_source.write_text("dummy source content", encoding="utf-8")
    f_runner.write_text("dummy runner content", encoding="utf-8")

    digest_bundle = hashlib.sha256()
    for f_item in (f_policy, f_source, f_runner):
        digest_bundle.update(f_item.name.encode("utf-8"))
        digest_bundle.update(b"\0")
        digest_bundle.update(f_item.read_bytes())
        digest_bundle.update(b"\0")
    bundle_hash = digest_bundle.hexdigest()

    return {
        "scorer_file": scorer_file,
        "eval_file": eval_file,
        "lineage_file": lineage_file,
        "scorer_hash": scorer_hash,
        "eval_hash": eval_hash,
        "lineage_hash": lineage_hash,
        "bias_tsv": bias_tsv,
        "manifest_file": manifest_file,
        "benchmark_file": benchmark_file,
        "mask_ledger": mask_ledger,
        "remask_audit": remask_audit,
        "return_manifest": return_manifest,
        "reference_root": ref_root,
        "bundle_hash": bundle_hash,
        "bundle_files": (f_policy, f_source, f_runner),
    }


def test_g_dm4_run_masked_holdout_eval_proceed(tmp_path):
    """
    G-DM4: approved+disabled_manual policy with matching hashes and masked inputs
    results in gate status != BLOCKED_POLICY (determined by decide_gate metrics)
    and config_pins asserting policy_mode=disabled_manual, pp3bp4_scored_calls=0, etc.
    """
    env_inputs = _create_mock_holdout_package(tmp_path)

    policy_data = {
        "schema": "bp4pp3-predictor-policy/2",
        "status": "approved",
        "mode": "disabled_manual",
        "predictor_source_hash": "a" * 64,
        "correction_hash": "b" * 64,
        "production_config_hash": env_inputs["scorer_hash"],
        "eval_config_hash": env_inputs["eval_hash"],
        "lineage_policy_hash": env_inputs["lineage_hash"],
        "runtime_bundle_hash": env_inputs["bundle_hash"],
        "decision_reference": "ADR-0012"
    }

    policy_path = tmp_path / "approved_policy.json"
    policy_path.write_text(json.dumps(policy_data))

    output_report = tmp_path / "report.txt"
    output_json = tmp_path / "report.json"

    # Invoke runner subprocess
    cmd = [
        sys.executable, "scripts/run_masked_holdout_eval.py",
        "--predictor-policy", str(policy_path),
        "--bias-tsv", str(env_inputs["bias_tsv"]),
        "--manifest", str(env_inputs["manifest_file"]),
        "--benchmark", str(env_inputs["benchmark_file"]),
        "--mask-ledger", str(env_inputs["mask_ledger"]),
        "--remask-audit", str(env_inputs["remask_audit"]),
        "--return-manifest", str(env_inputs["return_manifest"]),
        "--reference-root", str(env_inputs["reference_root"]),
        "--scorer-config", str(env_inputs["scorer_file"]),
        "--eval-config", str(env_inputs["eval_file"]),
        "--output-report", str(output_report),
        "--output-json", str(output_json),
    ]

    # In the RED test, this fails because schema v2/mode support isn't implemented yet,
    # causing PredictorPolicyError or exiting with BLOCKED_POLICY.
    # We assert the expected success properties which are currently RED.
    res = subprocess.run(cmd, capture_output=True, text=True)
    
    # We expect that when implemented, the exit code is 0 and status is not BLOCKED_POLICY.
    # In RED-first, this assertion will fail.
    assert res.returncode == 0, f"Subprocess failed: {res.stderr}"
    assert "BLOCKED_POLICY" not in res.stdout, "Policy should proceed, not block"

    # Load produced JSON report and check the config pins
    assert output_json.exists(), "Should have produced output report"
    report = json.loads(output_json.read_text(encoding="utf-8"))
    
    config_pins = report["report"]["config_pins"]
    assert config_pins["policy_mode"] == "disabled_manual"
    assert config_pins["pp3bp4_scored_calls"] == 0
    assert config_pins["pp3bp4_suppressed_counts"] == {"PP3": 1, "BP4": 1}
    assert config_pins["predictor_correction_applied"] is False


def test_g_dm5_run_masked_holdout_eval_proposed_blocked(tmp_path):
    """
    G-DM5: proposed+disabled_manual policy => BLOCKED_POLICY with no computed metrics.
    """
    env_inputs = _create_mock_holdout_package(tmp_path)

    policy_data = {
        "schema": "bp4pp3-predictor-policy/2",
        "status": "proposed",  # unapproved proposed status
        "mode": "disabled_manual",
        "predictor_source_hash": "a" * 64,
        "correction_hash": "b" * 64,
        "production_config_hash": env_inputs["scorer_hash"],
        "eval_config_hash": env_inputs["eval_hash"],
        "lineage_policy_hash": env_inputs["lineage_hash"],
        "runtime_bundle_hash": env_inputs["bundle_hash"],
        "decision_reference": "ADR-0012"
    }

    policy_path = tmp_path / "proposed_policy.json"
    policy_path.write_text(json.dumps(policy_data))

    cmd = [
        sys.executable, "scripts/run_masked_holdout_eval.py",
        "--predictor-policy", str(policy_path),
        "--bias-tsv", str(env_inputs["bias_tsv"]),
        "--manifest", str(env_inputs["manifest_file"]),
        "--benchmark", str(env_inputs["benchmark_file"]),
        "--mask-ledger", str(env_inputs["mask_ledger"]),
        "--remask-audit", str(env_inputs["remask_audit"]),
        "--return-manifest", str(env_inputs["return_manifest"]),
        "--reference-root", str(env_inputs["reference_root"]),
        "--scorer-config", str(env_inputs["scorer_file"]),
        "--eval-config", str(env_inputs["eval_file"]),
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    # Must fail closed with BLOCKED_POLICY in stdout/stderr
    assert "BLOCKED_POLICY" in res.stdout or "BLOCKED_POLICY" in res.stderr
    assert "precision=" not in res.stdout


def test_g_dm6_run_masked_holdout_eval_corrected_enabled_blocked(tmp_path):
    """
    G-DM6: approved+corrected_enabled policy => BLOCKED_POLICY (as it is out of scope).
    """
    env_inputs = _create_mock_holdout_package(tmp_path)

    policy_data = {
        "schema": "bp4pp3-predictor-policy/2",
        "status": "approved",
        "mode": "corrected_enabled",  # un-approved mode in this track
        "predictor_source_hash": "a" * 64,
        "correction_hash": "b" * 64,
        "production_config_hash": env_inputs["scorer_hash"],
        "eval_config_hash": env_inputs["eval_hash"],
        "lineage_policy_hash": env_inputs["lineage_hash"],
        "runtime_bundle_hash": env_inputs["bundle_hash"],
        "decision_reference": "ADR-0012"
    }

    policy_path = tmp_path / "enabled_policy.json"
    policy_path.write_text(json.dumps(policy_data))

    cmd = [
        sys.executable, "scripts/run_masked_holdout_eval.py",
        "--predictor-policy", str(policy_path),
        "--bias-tsv", str(env_inputs["bias_tsv"]),
        "--manifest", str(env_inputs["manifest_file"]),
        "--benchmark", str(env_inputs["benchmark_file"]),
        "--mask-ledger", str(env_inputs["mask_ledger"]),
        "--remask-audit", str(env_inputs["remask_audit"]),
        "--return-manifest", str(env_inputs["return_manifest"]),
        "--reference-root", str(env_inputs["reference_root"]),
        "--scorer-config", str(env_inputs["scorer_file"]),
        "--eval-config", str(env_inputs["eval_file"]),
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    assert "BLOCKED_POLICY" in res.stdout or "BLOCKED_POLICY" in res.stderr
    assert "precision=" not in res.stdout


def test_g_dm7_run_masked_holdout_eval_drift_blocked(tmp_path):
    """
    G-DM7: approved+disabled_manual policy but with a mutated configuration file
    byte => BLOCKED_POLICY (accidental byte drift detection).
    """
    env_inputs = _create_mock_holdout_package(tmp_path)

    policy_data = {
        "schema": "bp4pp3-predictor-policy/2",
        "status": "approved",
        "mode": "disabled_manual",
        "predictor_source_hash": "a" * 64,
        "correction_hash": "b" * 64,
        "production_config_hash": env_inputs["scorer_hash"],
        "eval_config_hash": env_inputs["eval_hash"],
        "lineage_policy_hash": env_inputs["lineage_hash"],
        "runtime_bundle_hash": env_inputs["bundle_hash"],
        "decision_reference": "ADR-0012"
    }

    policy_path = tmp_path / "drift_policy.json"
    policy_path.write_text(json.dumps(policy_data))

    # Test parametrized over mutations to scorer config, eval config, and lineage config
    for key_file in ("scorer_file", "eval_file", "lineage_file"):
        original_bytes = env_inputs[key_file].read_bytes()
        env_inputs[key_file].write_text("mutated config data", encoding="utf-8")

        cmd = [
            sys.executable, "scripts/run_masked_holdout_eval.py",
            "--predictor-policy", str(policy_path),
            "--bias-tsv", str(env_inputs["bias_tsv"]),
            "--manifest", str(env_inputs["manifest_file"]),
            "--benchmark", str(env_inputs["benchmark_file"]),
            "--mask-ledger", str(env_inputs["mask_ledger"]),
            "--remask-audit", str(env_inputs["remask_audit"]),
            "--return-manifest", str(env_inputs["return_manifest"]),
            "--reference-root", str(env_inputs["reference_root"]),
            "--scorer-config", str(env_inputs["scorer_file"]),
            "--eval-config", str(env_inputs["eval_file"]),
        ]

        res = subprocess.run(cmd, capture_output=True, text=True)
        assert "BLOCKED_POLICY" in res.stdout or "BLOCKED_POLICY" in res.stderr
        
        # Restore configuration
        env_inputs[key_file].write_bytes(original_bytes)


def test_g_dm8_run_masked_holdout_eval_legacy_blocked(tmp_path):
    """
    G-DM8: legacy v1 schema approved policy => BLOCKED_POLICY (never allows disabled).
    """
    env_inputs = _create_mock_holdout_package(tmp_path)

    # v1 policy has no mode field and old schema id
    policy_data = {
        "schema": "bp4pp3-predictor-policy",
        "status": "approved",
        "predictor_source_hash": "a" * 64,
        "correction_hash": "b" * 64,
        "decision_reference": "ADR-0010"
    }

    policy_path = tmp_path / "legacy_policy.json"
    policy_path.write_text(json.dumps(policy_data))

    cmd = [
        sys.executable, "scripts/run_masked_holdout_eval.py",
        "--predictor-policy", str(policy_path),
        "--bias-tsv", str(env_inputs["bias_tsv"]),
        "--manifest", str(env_inputs["manifest_file"]),
        "--benchmark", str(env_inputs["benchmark_file"]),
        "--mask-ledger", str(env_inputs["mask_ledger"]),
        "--remask-audit", str(env_inputs["remask_audit"]),
        "--return-manifest", str(env_inputs["return_manifest"]),
        "--reference-root", str(env_inputs["reference_root"]),
        "--scorer-config", str(env_inputs["scorer_file"]),
        "--eval-config", str(env_inputs["eval_file"]),
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    assert "BLOCKED_POLICY" in res.stdout or "BLOCKED_POLICY" in res.stderr


def test_g_dm9_configs_and_lineage_policy():
    """
    G-DM9: Removal parity verification: included_criteria == automatable_criteria
    (12 items), vocabulary retained, and PP3/BP4 records configured to deferred/deferred.
    """
    import yaml

    acmg_path = Path("configs/acmg/tsc.yaml")
    eval_path = Path("configs/eval/tsc2.yaml")
    lineage_path = Path("configs/eval/bias_lineage.yaml")

    assert acmg_path.is_file()
    assert eval_path.is_file()
    assert lineage_path.is_file()

    with open(acmg_path) as f:
        acmg_cfg = yaml.safe_load(f)
    with open(eval_path) as f:
        eval_cfg = yaml.safe_load(f)
    with open(lineage_path) as f:
        lineage_cfg = yaml.safe_load(f)

    included = acmg_cfg.get("included_criteria", [])
    automatable = eval_cfg.get("automatable_criteria", [])

    # Once Sonnet removes them, these assertions will pass
    assert "PP3" not in included, "PP3 should be absent from included_criteria"
    assert "BP4" not in included, "BP4 should be absent from included_criteria"
    assert "PP3" not in automatable, "PP3 should be absent from automatable_criteria"
    assert "BP4" not in automatable, "BP4 should be absent from automatable_criteria"

    assert len(included) == 12
    assert len(automatable) == 12
    assert set(included) == set(automatable)

    # Vocabulary is retained
    from raptor.scorer.config import VALID_CRITERIA
    assert "PP3" in VALID_CRITERIA
    assert "BP4" in VALID_CRITERIA
    assert "PP3" in acmg_cfg.get("acmg_criteria", {})
    assert "BP4" in acmg_cfg.get("acmg_criteria", {})

    # bias_lineage record deferred dispositions
    bp4_record = lineage_cfg["records"]["BP4"]
    pp3_record = lineage_cfg["records"]["PP3"]

    for code, record in (("BP4", bp4_record), ("PP3", pp3_record)):
        assert record["validation_disposition"] == "deferred", f"{code} validation_disposition must be deferred"
        assert record["production_disposition"] == "deferred", f"{code} production_disposition must be deferred"
        assert record["decision_dependency"] == "bp4pp3-predictor-policy", f"{code} decision_dependency mismatch"
        assert record.get("decision_rationale", "").strip() != "", f"{code} requires decision_rationale"


def test_g_dm10_end_to_end_suppression():
    """
    G-DM10: BIAS record containing PVS1 + PP3 + BP4 is filtered cleanly
    to PVS1 alone, with suppressed counts reflecting PP3 and BP4.
    """
    try:
        from raptor.eval.terminal_source import PolicyDisabledEvidenceSource
    except ImportError:
        pytest.fail("Missing terminal_source implementation")

    class DummySource:
        def get_evidence(self, variant_id):
            return (
                ("PVS1", "very_strong", "pathogenic"),
                ("PP3", "moderate", "pathogenic"),
                ("BP4", "supporting", "benign")
            )

    wrapped = PolicyDisabledEvidenceSource(DummySource())
    filtered = wrapped.get_evidence("v1")

    # PP3 & BP4 stripped, PVS1 retained
    assert filtered == (("PVS1", "very_strong", "pathogenic"),)
    assert wrapped.suppressed_counts == {"PP3": 1, "BP4": 1}


def test_g_dm11_accidental_drift_enforcement(tmp_path):
    """
    G-DM11: verify_runtime_bundle_hash validates the actual bytes of specified files;
    mutating any bundle file throws PredictorPolicyError and triggers runner block.
    """
    try:
        from raptor.eval.predictor_policy import (
            load_predictor_policy,
            verify_runtime_bundle_hash,
            PredictorPolicyError,
        )
    except ImportError:
        pytest.fail("Missing predictor_policy implementation")

    f1 = tmp_path / "predictor_policy.py"
    f2 = tmp_path / "terminal_source.py"
    f3 = tmp_path / "run_masked_holdout_eval.py"

    f1.write_text("source 1", encoding="utf-8")
    f2.write_text("source 2", encoding="utf-8")
    f3.write_text("source 3", encoding="utf-8")

    digest = hashlib.sha256()
    for f in (f1, f2, f3):
        digest.update(f.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(f.read_bytes())
        digest.update(b"\0")
    bundle_hash = digest.hexdigest()

    policy_data = {
        "schema": "bp4pp3-predictor-policy/2",
        "status": "approved",
        "mode": "disabled_manual",
        "predictor_source_hash": "a" * 64,
        "correction_hash": "b" * 64,
        "production_config_hash": "c" * 64,
        "eval_config_hash": "d" * 64,
        "lineage_policy_hash": "e" * 64,
        "runtime_bundle_hash": bundle_hash,
        "decision_reference": "ADR-0012"
    }

    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy_data))
    policy = load_predictor_policy(policy_path)

    # Clean bundle verifies correctly
    verify_runtime_bundle_hash(policy, (f1, f2, f3))

    # Mutated file fails validation
    f1.write_text("tampered/drifted content", encoding="utf-8")
    with pytest.raises(PredictorPolicyError, match="runtime_bundle_hash mismatch|mismatch"):
        verify_runtime_bundle_hash(policy, (f1, f2, f3))


def test_g_dm12_alternate_config_mismatch(tmp_path):
    """
    G-DM12: Alternate --scorer-config or --eval-config paths that are byte-identical
    to the pinned policy hashes PROCEED, but any modification/threshold changes fail closed.
    """
    env_inputs = _create_mock_holdout_package(tmp_path)

    policy_data = {
        "schema": "bp4pp3-predictor-policy/2",
        "status": "approved",
        "mode": "disabled_manual",
        "predictor_source_hash": "a" * 64,
        "correction_hash": "b" * 64,
        "production_config_hash": env_inputs["scorer_hash"],
        "eval_config_hash": env_inputs["eval_hash"],
        "lineage_policy_hash": env_inputs["lineage_hash"],
        "runtime_bundle_hash": env_inputs["bundle_hash"],
        "decision_reference": "ADR-0012"
    }

    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy_data))

    # Create byte-identical alternate configurations
    alt_scorer = tmp_path / "alt_scorer.yaml"
    alt_eval = tmp_path / "alt_eval.yaml"
    alt_scorer.write_bytes(env_inputs["scorer_file"].read_bytes())
    alt_eval.write_bytes(env_inputs["eval_file"].read_bytes())

    # Byte-identical alternate paths -> PROCEED
    cmd_alt = [
        sys.executable, "scripts/run_masked_holdout_eval.py",
        "--predictor-policy", str(policy_path),
        "--bias-tsv", str(env_inputs["bias_tsv"]),
        "--manifest", str(env_inputs["manifest_file"]),
        "--benchmark", str(env_inputs["benchmark_file"]),
        "--mask-ledger", str(env_inputs["mask_ledger"]),
        "--remask-audit", str(env_inputs["remask_audit"]),
        "--return-manifest", str(env_inputs["return_manifest"]),
        "--reference-root", str(env_inputs["reference_root"]),
        "--scorer-config", str(alt_scorer),
        "--eval-config", str(alt_eval),
    ]
    res_alt = subprocess.run(cmd_alt, capture_output=True, text=True)
    assert res_alt.returncode == 0
    assert "BLOCKED_POLICY" not in res_alt.stdout

    # Modified alternate configs BEFORE invocation -> BLOCKED_POLICY
    alt_scorer.write_text("mutated scorer threshold bytes", encoding="utf-8")
    res_drift = subprocess.run(cmd_alt, capture_output=True, text=True)
    assert "BLOCKED_POLICY" in res_drift.stdout or "BLOCKED_POLICY" in res_drift.stderr


def test_g_dm13_authorization_neutrality():
    """
    G-DM13: Policy approval/mode has NO influence on the metric-driven decide_gate
    or decide_scope_gate results; the runner remains strictly authorization-neutral.
    """
    try:
        from scripts.run_masked_holdout_eval import compute_report_scope_gate
    except ImportError:
        pytest.fail("Missing run_masked_holdout_eval implementation")

    from conftest import make_eval_config, Metrics
    from raptor.eval.model import ScopeGateDecision
    from test_scope_gate import make_v2_auth_config, make_oracle_thresholds

    # Gate decision depends on Metrics, never the Policy Mode
    config = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds=make_oracle_thresholds(),
        scope_authorization=make_v2_auth_config()
    )
    m_truncating = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"path_called": 40, "benign_called": 1, "path_actual": 40, "benign_actual": 1},
        stratum="truncating", gating=True, benign_precision=1.0, benign_recall=1.0
    )
    m_truncating.precision_lb = 0.96
    m_truncating.recall_lb = 0.96

    metrics = {"truncating": m_truncating}

    result = compute_report_scope_gate(metrics, config, skipped=set())
    assert isinstance(result, ScopeGateDecision)
    assert result.research_scope_flags["truncating_pathogenic_research_scope_validated"] is True


def test_g_dm14_lineage_consistency_negative_control():
    """
    G-DM14: Negative control proving that removing PP3/BP4 from automatable_criteria
    while leaving their bias_lineage.yaml disposition as 'allowed' raises
    LineageRegistryMismatchError with set 'omitted_without_disposition'.
    """
    try:
        from raptor.eval.lineage_policy import load_lineage_policy
        from raptor.eval.lineage_registry import (
            LineageRegistryMismatchError,
            assert_registry_consistency,
        )
        from raptor.eval.config import load_config as load_eval_config
        from raptor.scorer.config import load_config as load_scorer_config
    except ImportError:
        pytest.fail("Missing lineage registry implementation")

    from dataclasses import replace

    policy_path = Path("configs/eval/bias_lineage.yaml")
    scorer_path = Path("configs/acmg/tsc.yaml")
    eval_path = Path("configs/eval/tsc2.yaml")

    policy = load_lineage_policy(policy_path)
    scorer_config = load_scorer_config(scorer_path)
    eval_config = load_eval_config(eval_path)

    # Simulate omission: remove PP3 & BP4 from automatable and included criteria,
    # but keep them 'allowed' in the policy (since bias_lineage.yaml has them as allowed before Sonnet edit).
    test_included = tuple(c for c in scorer_config.included_criteria if c not in {"PP3", "BP4"})
    test_scorer = replace(scorer_config, included_criteria=test_included)
    test_eval = replace(eval_config, automatable_criteria=test_included)

    # Registry check fails closed because of the omitted PP3 & BP4 with allowed disposition
    with pytest.raises(LineageRegistryMismatchError) as exc:
        assert_registry_consistency(policy, test_scorer, test_eval)

    assert "omitted_without_disposition" in exc.value.sets_by_kind
    assert exc.value.sets_by_kind["omitted_without_disposition"] == {"PP3", "BP4"}
