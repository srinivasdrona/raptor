import pytest
import json
import subprocess
import sys
import os
from pathlib import Path


def test_ta1_dev_export_blocked_and_deterministic(tmp_path):
    """T-A1 dev export blocked.

    Verify scripts/export_dev_vcf.py:
    1. Reads dev variant_id only (represented as canonical SPDI string), with no labels.
    2. Writes a deterministic JSON status artifact to the specified path when reference/runtime is absent.
    3. The written JSON has status 'BLOCKED_DATA' and lists the four specific missing prerequisites.
    4. Substantive content/hashes are deterministic (timestamp-excluded or sorted).
    """
    script_path = Path("scripts/export_dev_vcf.py")
    status_output = tmp_path / "tsc_pp3bp4_dev_score_acquisition_2026-07.json"

    # Red validation: fail only for missing implementation
    if not script_path.exists():
        pytest.fail(f"implementation missing: {script_path}")

    # Use a small valid benchmark fixture with canonical SPDI IDs (not HGVS)
    dummy_benchmark = tmp_path / "benchmark.jsonl"
    dummy_benchmark.write_text(
        json.dumps({"variant_id": "NC_000009.12:12345:A:G", "label": "P", "variant_class": "missense"}) + "\n" +
        json.dumps({"variant_id": "NC_000016.10:54321:C:T", "label": "B", "variant_class": "missense"}) + "\n"
    )

    # Use the real configs/eval/tsc2.yaml (Correction 8)
    real_eval_config = Path("configs/eval/tsc2.yaml")
    if not real_eval_config.exists():
        pytest.fail(f"Missing real eval config: {real_eval_config}")

    # Run script expecting it to output BLOCKED_DATA with nonexistent reference root
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"

    cmd = [
        sys.executable,
        str(script_path),
        "--benchmark", str(dummy_benchmark),
        "--eval-config", str(real_eval_config),
        "--reference-root", "nonexistent/reference/root/path",
        "--benchmark-snapshot", "clinvar_2026-07-07",
        "--out-dir", str(tmp_path / "external-dev-dir"),
        "--status-output", str(status_output),
        "--report-date", "2026-07-19" # Explicit report-date / as-of for deterministic hash
    ]

    res = subprocess.run(cmd, capture_output=True, text=True, env=env)
    
    # Check if the status_output file is written and parse it.
    assert status_output.is_file(), f"Script failed to write status output. Stderr: {res.stderr}\nStdout: {res.stdout}"

    data = json.loads(status_output.read_text(encoding="utf-8"))

    # Verify status is BLOCKED_DATA
    assert data["status"] == "BLOCKED_DATA"

    # Verify all four missing prerequisites are listed
    missing = data.get("missing_prerequisites", [])
    assert any("reference" in m.lower() or "fasta" in m.lower() for m in missing), "Missing reference root prerequisite"
    assert any("nirvana" in m.lower() or "dbnsfp" in m.lower() or "annotation" in m.lower() for m in missing), "Missing structured REVEL runtime prerequisite"
    assert any("version" in m.lower() for m in missing), "Missing predictor/data version pin prerequisite"
    assert any("license" in m.lower() for m in missing), "Missing license/permitted-use record prerequisite"

    # Verify reference pins
    ref_pins = data.get("reference_pins", [])
    assert "NC_000016.10" in ref_pins
    assert "NC_000009.12" in ref_pins

    # Verify no labels are present in any outputs
    assert "labels" not in status_output.read_text(encoding="utf-8")

    # Verify determinism: running twice with same inputs should yield identical JSON (content-hash identical)
    status_output_2 = tmp_path / "tsc_pp3bp4_dev_score_acquisition_2026-07_2.json"
    cmd2 = cmd.copy()
    cmd2[cmd2.index(str(status_output))] = str(status_output_2)
    subprocess.run(cmd2, capture_output=True, text=True, env=env)
    assert status_output_2.is_file()

    # Compare content (ignoring run-specific metadata if excluded, or checking exact match)
    js1 = json.loads(status_output.read_text(encoding="utf-8"))
    js2 = json.loads(status_output_2.read_text(encoding="utf-8"))
    assert js1 == js2


def test_cli_help_bootstrap():
    """T-A4/T-B8 check export_dev_vcf can run with a clean PYTHONPATH and shows help."""
    script_path = Path("scripts/export_dev_vcf.py")
    if not script_path.exists():
        pytest.fail(f"implementation missing: {script_path}")

    env = os.environ.copy()
    env["PYTHONPATH"] = "src"

    cmd = [sys.executable, str(script_path), "--help"]
    res = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert res.returncode == 0, f"CLI help failed under clean PYTHONPATH: {res.stderr}"
    assert "usage" in res.stdout.lower() or "help" in res.stdout.lower()
