import pytest
import json
import subprocess
import sys
import hashlib
from pathlib import Path

# All imports from raptor are done inside the test functions
# to ensure the test suite collects cleanly under pytest even
# when implementation elements are absent.

def _get_real_bundle_hash_and_files():
    f1 = Path("src/raptor/eval/predictor_policy.py")
    f2 = Path("src/raptor/eval/terminal_source.py")
    f3 = Path("scripts/run_masked_holdout_eval.py")
    
    files = [f1, f2, f3]
    sorted_files = sorted(files, key=lambda f: f.name)
    
    digest = hashlib.sha256()
    for f in sorted_files:
        digest.update(f.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(f.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest(), sorted_files


def _make_temp_policy_and_configs(tmp_path, status, mode, scorer_bytes=None, eval_bytes=None, lineage_bytes=None, packet_bytes=None):
    if scorer_bytes is None:
        scorer_bytes = b"scorer"
    if eval_bytes is None:
        eval_bytes = b"eval"
    if lineage_bytes is None:
        lineage_bytes = b"lineage"
    if packet_bytes is None:
        packet_bytes = b"packet"
        
    scorer_file = tmp_path / "tsc.yaml"
    eval_file = tmp_path / "tsc2.yaml"
    lineage_file = tmp_path / "bias_lineage.yaml"
    packet_file = tmp_path / "candidate_direction.yaml"
    
    scorer_file.write_bytes(scorer_bytes)
    eval_file.write_bytes(eval_bytes)
    lineage_file.write_bytes(lineage_bytes)
    packet_file.write_bytes(packet_bytes)
    
    scorer_hash = hashlib.sha256(scorer_bytes).hexdigest()
    eval_hash = hashlib.sha256(eval_bytes).hexdigest()
    lineage_hash = hashlib.sha256(lineage_bytes).hexdigest()
    packet_hash = hashlib.sha256(packet_bytes).hexdigest()
    
    bundle_hash, bundle_files = _get_real_bundle_hash_and_files()
        
    policy_data = {
        "schema": "bp4pp3-predictor-policy/2",
        "status": status,
        "mode": mode,
        "predictor_source_hash": "a" * 64,
        "correction_hash": "b" * 64,
        "production_config_hash": scorer_hash,
        "eval_config_hash": eval_hash,
        "lineage_policy_hash": lineage_hash,
        "packet_policy_hash": packet_hash,
        "runtime_bundle_hash": bundle_hash,
        "decision_reference": "ADR-0012"
    }
    
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy_data))
    
    from raptor.eval.predictor_policy import load_predictor_policy
    policy = load_predictor_policy(policy_path)
    
    return policy, scorer_file, eval_file, lineage_file, packet_file, bundle_files


def test_g_dm1_v2_loader_validation(tmp_path):
    """
    G-DM1: v2 loader accepts the exact closed v2 field set (including packet_policy_hash) and populates
    PredictorPolicy properties; rejects unknown/extra fields, missing required fields,
    unknown mode values, and non-64-hex hashes (including production, eval, lineage, packet, and bundle hashes).
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
        "packet_policy_hash": "f" * 64,
        "runtime_bundle_hash": "0" * 64,
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
    assert policy.packet_policy_hash == "f" * 64
    assert policy.runtime_bundle_hash == "0" * 64
    assert policy.decision_reference == "ADR-0012"
    assert policy.approved is True

    # 2. Reject unknown/extra fields
    extra_field = valid_v2.copy()
    extra_field["unknown_field"] = "value"
    with pytest.raises(PredictorPolicyError, match="unknown field"):
        load_predictor_policy(write_policy("extra.json", extra_field))

    # 3. Reject missing required v2 fields
    for field in ("mode", "lineage_policy_hash", "packet_policy_hash", "runtime_bundle_hash"):
        missing_field = valid_v2.copy()
        del missing_field[field]
        with pytest.raises(PredictorPolicyError, match="missing required field"):
            load_predictor_policy(write_policy(f"missing_{field}.json", missing_field))

    # 4. Reject unknown mode values
    bad_mode = valid_v2.copy()
    bad_mode["mode"] = "active_enforced"
    with pytest.raises(PredictorPolicyError, match="unknown mode"):
        load_predictor_policy(write_policy("bad_mode.json", bad_mode))

    # 5. Reject non-64-hex config/lineage/packet/bundle hashes
    for field in ("production_config_hash", "eval_config_hash", "lineage_policy_hash", "packet_policy_hash", "runtime_bundle_hash"):
        bad_hash = valid_v2.copy()
        bad_hash[field] = "not-64-hex"
        with pytest.raises(PredictorPolicyError, match="64-hex|hash|sha256"):
            load_predictor_policy(write_policy(f"bad_{field}.json", bad_hash))


def test_g_dm2_verify_disabled_config_hashes(tmp_path):
    """
    G-DM2: verify_disabled_config_hashes hashes the ACTUAL given config paths (scorer, eval, lineage, packet)
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
    packet_bytes = b"candidate direction configuration bytes"

    scorer_file = tmp_path / "tsc.yaml"
    eval_file = tmp_path / "tsc2.yaml"
    lineage_file = tmp_path / "bias_lineage.yaml"
    packet_file = tmp_path / "candidate_direction.yaml"

    scorer_file.write_bytes(scorer_bytes)
    eval_file.write_bytes(eval_bytes)
    lineage_file.write_bytes(lineage_bytes)
    packet_file.write_bytes(packet_bytes)

    scorer_hash = hashlib.sha256(scorer_bytes).hexdigest()
    eval_hash = hashlib.sha256(eval_bytes).hexdigest()
    lineage_hash = hashlib.sha256(lineage_bytes).hexdigest()
    packet_hash = hashlib.sha256(packet_bytes).hexdigest()

    policy_data = {
        "schema": "bp4pp3-predictor-policy/2",
        "status": "approved",
        "mode": "disabled_manual",
        "predictor_source_hash": "a" * 64,
        "correction_hash": "b" * 64,
        "production_config_hash": scorer_hash,
        "eval_config_hash": eval_hash,
        "lineage_policy_hash": lineage_hash,
        "packet_policy_hash": packet_hash,
        "runtime_bundle_hash": "c" * 64,
        "decision_reference": "ADR-0012"
    }

    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy_data))
    policy = load_predictor_policy(policy_path)

    # Passes when all match
    verify_disabled_config_hashes(policy, scorer_file, eval_file, lineage_file, packet_file)

    # Raises on any mismatch
    for bad_file, content in (
        (scorer_file, b"mismatched scorer"),
        (eval_file, b"mismatched eval"),
        (lineage_file, b"mismatched lineage"),
        (packet_file, b"mismatched packet"),
    ):
        original_bytes = bad_file.read_bytes()
        bad_file.write_bytes(content)
        with pytest.raises(PredictorPolicyError, match="mismatch|hash"):
            verify_disabled_config_hashes(policy, scorer_file, eval_file, lineage_file, packet_file)
        bad_file.write_bytes(original_bytes)  # restore

    # Raises on missing file
    missing_file = tmp_path / "missing.yaml"
    with pytest.raises(PredictorPolicyError, match="not found|missing"):
        verify_disabled_config_hashes(policy, missing_file, eval_file, lineage_file, packet_file)


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


def test_g_dm4_offline_seams_composition(tmp_path):
    """
    G-DM4: offline unit composition:
    - Build a contract-valid BiasEvidenceSource (one canonical manifest row + single BIAS TSV row + FakeCanonicalNormalizer).
    - Write temp post-removal configs/lineage/packet.
    - Write approved v2 policy whose config hashes match those temp bytes and whose runtime_bundle_hash is the REAL repo bundle hash.
    - resolve_policy_state(...) == ("APPROVED_DISABLED", reason).
    - build_policy_evidence_source(source, state) wraps it in PolicyDisabledEvidenceSource.
    - build_disabled_policy_pins called EXACTLY per signature build_disabled_policy_pins(policy, wrapped_source, scorer_cfg, eval_cfg, lineage_policy)
    NO subprocess, NO benchmark/reference/mask pretense, NO 2,577-row TSV.
    """
    try:
        from scripts.run_masked_holdout_eval import (
            resolve_policy_state,
            build_policy_evidence_source,
            build_disabled_policy_pins,
        )
        from raptor.eval.predictor_policy import load_predictor_policy
        from raptor.eval.lineage_policy import load_lineage_policy
    except ImportError as exc:
        pytest.fail(f"Missing implementation seams: {exc}")

    from test_live_source import _source, FakeCanonicalNormalizer

    canonical_id = "NC_000002.11:26684722:G:A"
    manifest_rows = [{
        "variant_id": canonical_id,
        "vcf_key": "chr2:26684723:G:A",
        "accession": "NC_000002.11",
        "contig": "chr2"
    }]
    bias_rows = [{
        "chromosome": "chr2",
        "position": 26684723,
        "ref": "G",
        "alt": "A",
        "classification": "pathogenic",
        "criteria": {
            "pp3": (3, "strong revel"),
            "bp4": (1, "supporting")
        }
    }]

    mapping = {
        ("chr2", 26684723, "G", "A", "NC_000002.11"): canonical_id,
    }
    normalizer = FakeCanonicalNormalizer(mapping)

    # Copy current configs to temp
    scorer_bytes = Path("configs/acmg/tsc.yaml").read_bytes()
    eval_bytes = Path("configs/eval/tsc2.yaml").read_bytes()
    lineage_bytes = Path("configs/eval/bias_lineage.yaml").read_bytes()
    packet_bytes = Path("configs/packet/candidate_direction.yaml").read_bytes()

    scorer_path = tmp_path / "tsc.yaml"
    eval_path = tmp_path / "tsc2.yaml"
    lineage_path = tmp_path / "bias_lineage.yaml"
    packet_path = tmp_path / "candidate_direction.yaml"

    scorer_path.write_bytes(scorer_bytes)
    eval_path.write_bytes(eval_bytes)
    lineage_path.write_bytes(lineage_bytes)
    packet_path.write_bytes(packet_bytes)

    scorer_hash = hashlib.sha256(scorer_bytes).hexdigest()
    eval_hash = hashlib.sha256(eval_bytes).hexdigest()
    lineage_hash = hashlib.sha256(lineage_bytes).hexdigest()
    packet_hash = hashlib.sha256(packet_bytes).hexdigest()

    from raptor.eval.config import load_config as load_eval_config
    from raptor.scorer.config import load_config as load_scorer_config

    eval_cfg = load_eval_config(eval_path)
    scorer_cfg = load_scorer_config(scorer_path)
    lineage_policy = load_lineage_policy(lineage_path)

    # Build pure BiasEvidenceSource offline
    source = _source(
        tmp_path / "evidence_src",
        bias_rows=bias_rows,
        manifest_rows=manifest_rows,
        normalizer=normalizer,
        eval_config=eval_cfg,
        scorer_config=scorer_cfg,
    )

    # Get actual real bundle hash (sorted properly by name)
    real_bundle_hash, bundle_files = _get_real_bundle_hash_and_files()

    policy_data = {
        "schema": "bp4pp3-predictor-policy/2",
        "status": "approved",
        "mode": "disabled_manual",
        "predictor_source_hash": "a" * 64,
        "correction_hash": "b" * 64,
        "production_config_hash": scorer_hash,
        "eval_config_hash": eval_hash,
        "lineage_policy_hash": lineage_hash,
        "packet_policy_hash": packet_hash,
        "runtime_bundle_hash": real_bundle_hash,
        "decision_reference": "ADR-0012"
    }

    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy_data))
    policy = load_predictor_policy(policy_path)

    # 1. resolve_policy_state == APPROVED_DISABLED (now with packet_path seam)
    state, reason = resolve_policy_state(
        policy, scorer_path, eval_path, lineage_path, packet_path, bundle_files
    )
    assert state == "APPROVED_DISABLED", f"Expected APPROVED_DISABLED, got {state} ({reason})"

    # 2. build_policy_evidence_source wraps BiasEvidenceSource
    wrapped_source = build_policy_evidence_source(source, state)
    from raptor.eval.terminal_source import PolicyDisabledEvidenceSource
    assert isinstance(wrapped_source, PolicyDisabledEvidenceSource)

    # Retrieve evidence to count suppression
    wrapped_source.get_evidence(canonical_id)

    # 3. build_disabled_policy_pins called EXACTLY per signature with 5 arguments
    pins = build_disabled_policy_pins(policy, wrapped_source, scorer_cfg, eval_cfg, lineage_policy)
    assert pins["policy_mode"] == "disabled_manual"
    assert pins["pp3bp4_scored_calls"] == 0
    assert pins["pp3bp4_suppressed_counts"] == {"PP3": 1, "BP4": 1}
    assert pins["pp3bp4_lineage_disposition"] == "deferred"
    assert pins["predictor_correction_applied"] is False


def test_g_dm5_resolve_policy_state_proposed(tmp_path):
    """
    G-DM5: Proposed status + disabled_manual mode => PROPOSED_DISABLED.
    """
    try:
        from scripts.run_masked_holdout_eval import resolve_policy_state
    except ImportError:
        pytest.fail("Missing resolve_policy_state implementation")

    policy, s_file, e_file, l_file, p_file, b_files = _make_temp_policy_and_configs(
        tmp_path, "proposed", "disabled_manual"
    )

    state, reason = resolve_policy_state(policy, s_file, e_file, l_file, p_file, b_files)
    assert state == "PROPOSED_DISABLED"
    assert "proposed" in reason.lower()


def test_g_dm6_resolve_policy_state_corrected_enabled_blocked(tmp_path):
    """
    G-DM6: approved status + corrected_enabled mode => CORRECTED_ENABLED_OUT_OF_SCOPE.
    """
    try:
        from scripts.run_masked_holdout_eval import resolve_policy_state
    except ImportError:
        pytest.fail("Missing resolve_policy_state implementation")

    policy, s_file, e_file, l_file, p_file, b_files = _make_temp_policy_and_configs(
        tmp_path, "approved", "corrected_enabled"
    )

    state, reason = resolve_policy_state(policy, s_file, e_file, l_file, p_file, b_files)
    assert state == "CORRECTED_ENABLED_OUT_OF_SCOPE"


@pytest.mark.parametrize("mutilated_file", ["scorer", "eval", "lineage", "packet"])
def test_g_dm7_resolve_policy_state_drift_blocked(tmp_path, mutilated_file):
    """
    G-DM7: approved + disabled_manual but config/policy byte mismatch => CONFIG_DRIFT.
    """
    try:
        from scripts.run_masked_holdout_eval import resolve_policy_state
    except ImportError:
        pytest.fail("Missing resolve_policy_state implementation")

    policy, s_file, e_file, l_file, p_file, b_files = _make_temp_policy_and_configs(
        tmp_path, "approved", "disabled_manual"
    )

    if mutilated_file == "scorer":
        s_file.write_bytes(b"mutilated scorer")
    elif mutilated_file == "eval":
        e_file.write_bytes(b"mutilated eval")
    elif mutilated_file == "lineage":
        l_file.write_bytes(b"mutilated lineage")
    elif mutilated_file == "packet":
        p_file.write_bytes(b"mutilated packet")

    state, reason = resolve_policy_state(policy, s_file, e_file, l_file, p_file, b_files)
    assert state == "CONFIG_DRIFT"


def test_g_dm8_resolve_policy_state_legacy_blocked(tmp_path):
    """
    G-DM8: Legacy v1 policy structure (no mode field) => UNSUPPORTED_MODE.
    """
    try:
        from scripts.run_masked_holdout_eval import resolve_policy_state
        from raptor.eval.predictor_policy import load_predictor_policy
    except ImportError:
        pytest.fail("Missing resolve_policy_state implementation")

    policy_data = {
        "schema": "bp4pp3-predictor-policy",
        "status": "approved",
        "predictor_source_hash": "a" * 64,
        "correction_hash": "b" * 64,
        "decision_reference": "ADR-0010"
    }

    policy_path = tmp_path / "legacy_policy.json"
    policy_path.write_text(json.dumps(policy_data))
    policy = load_predictor_policy(policy_path)

    _, s_file, e_file, l_file, p_file, b_files = _make_temp_policy_and_configs(
        tmp_path, "approved", "disabled_manual"
    )

    state, reason = resolve_policy_state(policy, s_file, e_file, l_file, p_file, b_files)
    assert state == "UNSUPPORTED_MODE"


def test_g_dm8_terminal_runner_blocked_policy_subprocess(tmp_path):
    """
    Protected runner blocked subprocess test (requires no mock clinical files):
    Missing policy or unapproved policy fails closed returning status 0 with BLOCKED_POLICY.
    """
    script_path = Path("scripts/run_masked_holdout_eval.py")
    if not script_path.exists():
        pytest.skip("run_masked_holdout_eval.py not found")

    # 1. Missing policy file
    res = subprocess.run([sys.executable, str(script_path), "--predictor-policy", str(tmp_path / "missing.json")], capture_output=True, text=True)
    assert "BLOCKED_POLICY" in res.stdout or "BLOCKED_POLICY" in res.stderr
    assert "precision=" not in res.stdout

    # 2. Unapproved policy file
    unapproved = tmp_path / "unapproved.json"
    unapproved.write_text(json.dumps({
        "schema": "bp4pp3-predictor-policy",
        "status": "rejected",
        "predictor_source_hash": "a" * 64,
        "correction_hash": "b" * 64,
        "decision_reference": "ADR-0010"
    }))
    res3 = subprocess.run([sys.executable, str(script_path), "--predictor-policy", str(unapproved)], capture_output=True, text=True)
    assert "BLOCKED_POLICY" in res3.stdout or "BLOCKED_POLICY" in res3.stderr
    assert "precision=" not in res3.stdout


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

    # Vocabulary is retained (imported from eval config to resolve authorship defect)
    from raptor.eval.config import VALID_CRITERIA
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
    G-DM10: PolicyDisabledEvidenceSource wrapped dummy source that DEFINES variant_ids
    yields zero emitted PP3/BP4, a counted suppression of 2, and still emits PVS1.
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
        "v1": (
            ("PVS1", "very_strong", "pathogenic"),
            ("PP3", "moderate", "pathogenic"),
            ("BP4", "supporting", "benign")
        )
    }

    wrapped = PolicyDisabledEvidenceSource(DummySource(raw_evidence))
    filtered = wrapped.get_evidence("v1")

    # PP3 & BP4 stripped, PVS1 retained
    assert filtered == (("PVS1", "very_strong", "pathogenic"),)
    assert wrapped.suppressed_counts == {"PP3": 1, "BP4": 1}


def test_g_dm11_accidental_drift_enforcement(tmp_path):
    """
    G-DM11: verify_runtime_bundle_hash validates the actual bytes of specified files (sorted by name);
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

    files = [f1, f2, f3]
    sorted_files = sorted(files, key=lambda f: f.name)

    digest = hashlib.sha256()
    for f in sorted_files:
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
        "packet_policy_hash": "f" * 64,
        "runtime_bundle_hash": bundle_hash,
        "decision_reference": "ADR-0012"
    }

    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy_data))
    policy = load_predictor_policy(policy_path)

    # Clean bundle verifies correctly with sorted files
    verify_runtime_bundle_hash(policy, sorted_files)

    # Mutated file fails validation
    f1.write_text("tampered/drifted content", encoding="utf-8")
    with pytest.raises(PredictorPolicyError, match="runtime_bundle_hash mismatch|mismatch"):
        verify_runtime_bundle_hash(policy, sorted_files)


def test_g_dm12_verify_disabled_config_hashes_unit(tmp_path):
    """
    G-DM12: verify_disabled_config_hashes directly verifies byte-identical alternate scorer/eval/lineage/packet paths,
    raising PredictorPolicyError on modified config files. (NO subprocess)
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
    packet_bytes = b"packet direction configuration bytes"

    # Create original config files
    scorer_file = tmp_path / "tsc.yaml"
    eval_file = tmp_path / "tsc2.yaml"
    lineage_file = tmp_path / "bias_lineage.yaml"
    packet_file = tmp_path / "candidate_direction.yaml"

    scorer_file.write_bytes(scorer_bytes)
    eval_file.write_bytes(eval_bytes)
    lineage_file.write_bytes(lineage_bytes)
    packet_file.write_bytes(packet_bytes)

    scorer_hash = hashlib.sha256(scorer_bytes).hexdigest()
    eval_hash = hashlib.sha256(eval_bytes).hexdigest()
    lineage_hash = hashlib.sha256(lineage_bytes).hexdigest()
    packet_hash = hashlib.sha256(packet_bytes).hexdigest()

    policy_data = {
        "schema": "bp4pp3-predictor-policy/2",
        "status": "approved",
        "mode": "disabled_manual",
        "predictor_source_hash": "a" * 64,
        "correction_hash": "b" * 64,
        "production_config_hash": scorer_hash,
        "eval_config_hash": eval_hash,
        "lineage_policy_hash": lineage_hash,
        "packet_policy_hash": packet_hash,
        "runtime_bundle_hash": "c" * 64,
        "decision_reference": "ADR-0012"
    }

    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy_data))
    policy = load_predictor_policy(policy_path)

    # 1. Byte-identical alternate paths -> PASS
    alt_dir = tmp_path / "alt"
    alt_dir.mkdir()
    alt_scorer = alt_dir / "tsc.yaml"
    alt_eval = alt_dir / "tsc2.yaml"
    alt_lineage = alt_dir / "bias_lineage.yaml"
    alt_packet = alt_dir / "candidate_direction.yaml"

    alt_scorer.write_bytes(scorer_bytes)
    alt_eval.write_bytes(eval_bytes)
    alt_lineage.write_bytes(lineage_bytes)
    alt_packet.write_bytes(packet_bytes)

    verify_disabled_config_hashes(policy, alt_scorer, alt_eval, alt_lineage, alt_packet)

    # 2. Changed byte in any of the four -> PredictorPolicyError
    for alt_file, original in (
        (alt_scorer, scorer_bytes),
        (alt_eval, eval_bytes),
        (alt_lineage, lineage_bytes),
        (alt_packet, packet_bytes),
    ):
        alt_file.write_text("changed content for threshold/scope/auth", encoding="utf-8")
        with pytest.raises(PredictorPolicyError, match="mismatch|hash"):
            verify_disabled_config_hashes(policy, alt_scorer, alt_eval, alt_lineage, alt_packet)
        alt_file.write_bytes(original)  # restore


def test_g_dm13_authorization_neutrality_unit():
    """
    G-DM13: Policy approval/mode has NO influence on the metric-driven decide_gate,
    decide_scope_gate or compute_report_scope_gate results; the runner remains strictly authorization-neutral.
    """
    try:
        from raptor.eval.gate import decide_gate
        from raptor.eval.scope_gate import decide_scope_gate
        from scripts.run_masked_holdout_eval import compute_report_scope_gate
    except ImportError:
        pytest.fail("Missing gate/scope implementation")

    import inspect
    # Confirm they do not accept any policy / status / mode parameters in their signatures
    for func in (decide_gate, decide_scope_gate, compute_report_scope_gate):
        sig = inspect.signature(func)
        assert "policy" not in sig.parameters
        assert "status" not in sig.parameters
        assert "mode" not in sig.parameters
        assert "policy_mode" not in sig.parameters

    # Run them with passing and failing metrics and verify they behave normally without any policy override
    from tests.eval.factories import (
        Metrics,
        make_eval_config,
        make_oracle_thresholds,
        make_v2_auth_config,
    )

    # PASSING CASE (distinct Metrics objects for each stratum with passing pathogenic and benign bounds)
    passing_config = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds=make_oracle_thresholds(),
        scope_authorization=make_v2_auth_config()
    )
    m_missense_ok = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
        stratum="missense", gating=True, benign_precision=1.0, benign_recall=1.0
    )
    m_missense_ok.precision_lb = 0.98
    m_missense_ok.recall_lb = 0.98
    m_missense_ok.benign_precision_lb = 0.98
    m_missense_ok.benign_recall_lb = 0.98

    m_truncating_ok = Metrics(
        precision=1.0, recall=1.0, concordance=1.0,
        counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
        stratum="truncating", gating=True, benign_precision=1.0, benign_recall=1.0
    )
    m_truncating_ok.precision_lb = 0.98
    m_truncating_ok.recall_lb = 0.98
    m_truncating_ok.benign_precision_lb = 0.98
    m_truncating_ok.benign_recall_lb = 0.98

    passing_metrics = {"missense": m_missense_ok, "truncating": m_truncating_ok}

    # FAILING CASE (distinct Metrics objects for each stratum with failing pathogenic and benign bounds)
    failing_config = make_eval_config(
        min_count_per_class=36,
        oracle_thresholds=make_oracle_thresholds(),
        scope_authorization=make_v2_auth_config()
    )
    m_missense_fail = Metrics(
        precision=0.4, recall=0.4, concordance=0.4,
        counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
        stratum="missense", gating=True, benign_precision=0.4, benign_recall=0.4
    )
    m_missense_fail.precision_lb = 0.3
    m_missense_fail.recall_lb = 0.3
    m_missense_fail.benign_precision_lb = 0.3
    m_missense_fail.benign_recall_lb = 0.3

    m_truncating_fail = Metrics(
        precision=0.4, recall=0.4, concordance=0.4,
        counts={"path_called": 40, "benign_called": 40, "path_actual": 40, "benign_actual": 40},
        stratum="truncating", gating=True, benign_precision=0.4, benign_recall=0.4
    )
    m_truncating_fail.precision_lb = 0.3
    m_truncating_fail.recall_lb = 0.3
    m_truncating_fail.benign_precision_lb = 0.3
    m_truncating_fail.benign_recall_lb = 0.3

    failing_metrics = {"missense": m_missense_fail, "truncating": m_truncating_fail}

    # Verify verdicts with no policy intervention
    d_pass = decide_gate(passing_metrics, passing_config)
    d_fail = decide_gate(failing_metrics, failing_config)
    assert d_pass.vus_authorized is True
    assert d_fail.vus_authorized is False

    sd_pass = compute_report_scope_gate(passing_metrics, passing_config)
    sd_fail = compute_report_scope_gate(failing_metrics, failing_config)
    assert sd_pass.research_scope_flags["truncating_pathogenic_research_scope_validated"] is True
    assert sd_fail.research_scope_flags["truncating_pathogenic_research_scope_validated"] is False

    # Also exercise decide_scope_gate directly
    sd_gate_pass = decide_scope_gate(passing_metrics, passing_config)
    sd_gate_fail = decide_scope_gate(failing_metrics, failing_config)
    assert sd_gate_pass.research_scope_flags["truncating_pathogenic_research_scope_validated"] is True
    assert sd_gate_fail.research_scope_flags["truncating_pathogenic_research_scope_validated"] is False


def test_g_dm14_lineage_consistency_negative_control():
    """
    G-DM14: Negative control proving that removing PP3/BP4 from automatable_criteria
    while forcing their validation_disposition/production_disposition to 'allowed' (via cloned record)
    raises LineageRegistryMismatchError with set 'omitted_without_disposition'.
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

    # 1. Clone live records and force allowed
    cloned_records = dict(policy.records)
    cloned_records["PP3"] = replace(
        cloned_records["PP3"],
        validation_disposition="allowed",
        production_disposition="allowed",
        decision_dependency="",
        decision_rationale=""
    )
    cloned_records["BP4"] = replace(
        cloned_records["BP4"],
        validation_disposition="allowed",
        production_disposition="allowed",
        decision_dependency="",
        decision_rationale=""
    )
    cloned_policy = replace(policy, records=cloned_records)

    # Remove PP3 & BP4 from included and automatable criteria
    test_included = tuple(c for c in scorer_config.included_criteria if c not in {"PP3", "BP4"})
    test_scorer = replace(scorer_config, included_criteria=test_included)
    test_eval = replace(eval_config, automatable_criteria=test_included)

    # Registry check fails closed because of the omitted PP3 & BP4 with allowed disposition
    with pytest.raises(LineageRegistryMismatchError) as exc:
        assert_registry_consistency(cloned_policy, test_scorer, test_eval)

    assert "omitted_without_disposition" in exc.value.sets_by_kind
    assert exc.value.sets_by_kind["omitted_without_disposition"] == {"PP3", "BP4"}


def test_g_dm16_packet_parity(tmp_path):
    """
    G-DM16: Packet parity verification:
    - candidate_direction.yaml keys must be exactly the post-removal set {PVS1,PM2,PM4,BA1,BS1,BP3,BP7}.
    - packet_policy_hash binds those exact bytes (governance).
    - Packet drift resolves to CONFIG_DRIFT inside resolve_policy_state.
    """
    try:
        from raptor.packet.config import load_candidate_direction_policy
        from scripts.run_masked_holdout_eval import resolve_policy_state
    except ImportError as exc:
        pytest.fail(f"Missing candidate_direction/runner seams: {exc}")

    # 1. Validate keys
    packet_path = Path("configs/packet/candidate_direction.yaml")
    assert packet_path.is_file()
    policy = load_candidate_direction_policy(packet_path)
    assert set(policy.criterion_strength_points.keys()) == {"PVS1", "PM2", "PM4", "BA1", "BS1", "BP3", "BP7"}

    # 2. Verify drift blocks resolve_policy_state
    temp_policy, s_file, e_file, l_file, p_file, b_files = _make_temp_policy_and_configs(
        tmp_path, "approved", "disabled_manual", packet_bytes=packet_path.read_bytes()
    )
    
    # Matching hash and path resolves to APPROVED_DISABLED
    state, reason = resolve_policy_state(temp_policy, s_file, e_file, l_file, p_file, b_files)
    assert state == "APPROVED_DISABLED"

    # Mutation to packet file byte => CONFIG_DRIFT
    p_file.write_bytes(b"mutilated packet bytes for drift")
    state_drift, reason_drift = resolve_policy_state(temp_policy, s_file, e_file, l_file, p_file, b_files)
    assert state_drift == "CONFIG_DRIFT"
