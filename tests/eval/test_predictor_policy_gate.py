import pytest
import json
import subprocess
import sys
from pathlib import Path

# Module doesn't exist yet
try:
    from raptor.eval.predictor_policy import (
        load_predictor_policy,
        verify_predictor_policy_hashes,
        PredictorPolicyError,
        PredictorPolicy,
    )
except ImportError:
    pass

# AC-G9
def test_acg9_predictor_policy_loader_fail_closed(tmp_path):
    # Missing file -> PredictorPolicyError
    with pytest.raises(PredictorPolicyError):
        load_predictor_policy(str(tmp_path / "missing.json"))

    # Malformed JSON
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{")
    with pytest.raises(PredictorPolicyError):
        load_predictor_policy(str(bad_json))

    def write_policy(name, data):
        p = tmp_path / name
        p.write_text(json.dumps(data))
        return str(p)

    valid_base = {
        "schema": "bp4pp3-predictor-policy",
        "status": "approved",
        "predictor_source_hash": "a" * 64,
        "correction_hash": "b" * 64,
        "decision_reference": "ADR-0010"
    }

    # Wrong schema
    wrong_schema = valid_base.copy()
    wrong_schema["schema"] = "other"
    with pytest.raises(PredictorPolicyError):
        load_predictor_policy(write_policy("wrong_schema.json", wrong_schema))

    # Blank decision reference
    blank_ref = valid_base.copy()
    blank_ref["decision_reference"] = "   "
    with pytest.raises(PredictorPolicyError):
        load_predictor_policy(write_policy("blank_ref.json", blank_ref))

    # Non-64 hex hash
    bad_hash = valid_base.copy()
    bad_hash["predictor_source_hash"] = "abc"
    with pytest.raises(PredictorPolicyError):
        load_predictor_policy(write_policy("bad_hash.json", bad_hash))

    # Missing field
    missing_field = valid_base.copy()
    del missing_field["correction_hash"]
    with pytest.raises(PredictorPolicyError):
        load_predictor_policy(write_policy("missing_field.json", missing_field))

    # Well-formed, non-approved
    non_approved = valid_base.copy()
    non_approved["status"] = "pending"
    p = load_predictor_policy(write_policy("non_approved.json", non_approved))
    assert not p.approved
    assert p.status == "pending"

    # Well-formed, approved
    p_approved = load_predictor_policy(write_policy("approved.json", valid_base))
    assert p_approved.approved
    assert p_approved.schema == "bp4pp3-predictor-policy"
    assert p_approved.status == "approved"
    assert p_approved.predictor_source_hash == "a" * 64


def test_predictor_policy_hashes_bind_spec_and_correction(tmp_path):
    spec = tmp_path / "spec.yaml"
    correction = tmp_path / "correction.py"
    spec.write_text("spec", encoding="utf-8")
    correction.write_text("correction", encoding="utf-8")
    import hashlib

    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps({
        "schema": "bp4pp3-predictor-policy",
        "status": "approved",
        "predictor_source_hash": hashlib.sha256(b"spec").hexdigest(),
        "correction_hash": hashlib.sha256(b"correction").hexdigest(),
        "decision_reference": "evaluation-only-test",
    }))
    policy = load_predictor_policy(policy_path)
    verify_predictor_policy_hashes(policy, spec, correction)

    correction.write_text("changed", encoding="utf-8")
    with pytest.raises(PredictorPolicyError, match="correction_hash"):
        verify_predictor_policy_hashes(policy, spec, correction)


def test_predictor_policy_can_bind_correction_bundle(tmp_path):
    spec = tmp_path / "spec.yaml"
    first = tmp_path / "a.py"
    second = tmp_path / "b.py"
    spec.write_text("spec", encoding="utf-8")
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    import hashlib

    digest = hashlib.sha256()
    for path in (first, second):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps({
        "schema": "bp4pp3-predictor-policy",
        "status": "approved",
        "predictor_source_hash": hashlib.sha256(b"spec").hexdigest(),
        "correction_hash": digest.hexdigest(),
        "decision_reference": "evaluation-only-test",
    }))
    verify_predictor_policy_hashes(
        load_predictor_policy(policy_path),
        spec,
        (first, second),
    )

# AC-G8
def test_acg8_terminal_runner_blocked_policy(tmp_path):
    # scripts/run_masked_holdout_eval.py doesn't exist yet, but we test the requirement
    script_path = Path("scripts/run_masked_holdout_eval.py")
    if not script_path.exists():
        # skip if script not there to avoid failing before doer creates it
        # Actually, requirements say "Write authorized tests AC-G1..G9 before implementation."
        # If the test fails because the script doesn't exist, that is a clean RED.
        pass

    # The terminal runner requires --predictor-policy PATH.
    # Missing/unapproved -> GateDecision(status="BLOCKED_POLICY", vus_authorized=False) and NO METRICS.

    # Let's run it without the flag. It should fail (exit code != 0)
    res = subprocess.run([sys.executable, str(script_path)], capture_output=True, text=True)
    assert res.returncode != 0
    assert "predictor-policy" in res.stderr

    # Let's provide a malformed policy
    bad_policy = tmp_path / "bad_policy.json"
    bad_policy.write_text("{}")
    res2 = subprocess.run([sys.executable, str(script_path), "--predictor-policy", str(bad_policy)], capture_output=True, text=True)
    # The requirement says it emits GateDecision(status='BLOCKED_POLICY', vus_authorized=false) with no metrics.
    # We check stdout/stderr for BLOCKED_POLICY.
    assert "BLOCKED_POLICY" in res2.stdout or "BLOCKED_POLICY" in res2.stderr
    assert "vus_authorized=False" in res2.stdout or "vus_authorized=False" in res2.stderr or "vus_authorized=false" in res2.stdout.lower() or "vus_authorized=false" in res2.stderr.lower()

    # It must compute no metrics. If report body is printed, it should not have strata.
    assert "precision=" not in res2.stdout

    # Now with well-formed but unapproved policy
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
