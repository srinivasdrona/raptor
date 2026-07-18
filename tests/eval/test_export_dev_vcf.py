import pytest
import json
import subprocess
import sys
from pathlib import Path


def test_ta1_dev_export_blocked_and_deterministic(tmp_path):
    """T-A1 dev export blocked.

    Verify scripts/export_dev_vcf.py:
    1. Reads dev variant_id only, with no labels.
    2. Writes a deterministic JSON status artifact to the specified path when reference/runtime is absent.
    3. The written JSON has status 'BLOCKED_DATA' and lists the four specific missing prerequisites.
    4. Substantive content/hashes are deterministic (timestamp-excluded or sorted).
    """
    script_path = Path("scripts/export_dev_vcf.py")
    status_output = tmp_path / "tsc_pp3bp4_dev_score_acquisition_2026-07.json"

    # Since production is not yet implemented, running this script via subprocess
    # will fail or show missing file/module error in the RED state. That's the expected RED state.
    # To test the requirement thoroughly, we assert that the script behaves as expected:
    # We can write a test that runs the script and verifies its outputs if it exists,
    # or fails with a clean ModuleNotFoundError/FileNotFoundError/pytest.fail if not implemented.
    if not script_path.exists():
        pytest.fail(f"implementation missing: {script_path}")

    # Create dummy benchmark input to run the script
    dummy_benchmark = tmp_path / "benchmark.jsonl"
    dummy_benchmark.write_text(
        json.dumps({"variant_id": "NC_000009.12:g.12345A>G", "label": "P", "variant_class": "missense"}) + "\n"
    )

    dummy_config = tmp_path / "tsc2.yaml"
    dummy_config.write_text("split:\n  seed: 20260701\n  holdout_fraction: 0.7\n")

    # Run script expecting it to output BLOCKED_DATA
    cmd = [
        sys.executable,
        str(script_path),
        "--benchmark", str(dummy_benchmark),
        "--eval-config", str(dummy_config),
        "--benchmark-snapshot", "clinvar_2026-07-07",
        "--out-dir", str(tmp_path / "external-dev-dir"),
        "--status-output", str(status_output)
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    # The script should exit with 0 or a structured exit code on BLOCKED_DATA, or write the status_output
    # Let's check if the status_output file is written and parse it.
    assert status_output.is_file(), f"Script failed to write status output. Stderr: {res.stderr}"

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

    # Verify no labels are present in the output
    assert "labels" not in status_output.read_text(encoding="utf-8")

    # Verify determinism: running twice with same inputs should yield identical JSON (content-hash identical)
    status_output_2 = tmp_path / "tsc_pp3bp4_dev_score_acquisition_2026-07_2.json"
    cmd2 = cmd.copy()
    cmd2[-1] = str(status_output_2)
    subprocess.run(cmd2, capture_output=True, text=True)
    assert status_output_2.is_file()

    # Compare content hashes (ignoring run-specific metadata if excluded, or checking exact match)
    js1 = json.loads(status_output.read_text(encoding="utf-8"))
    js2 = json.loads(status_output_2.read_text(encoding="utf-8"))
    # Exclude timestamp if any, or assert they are byte-identical
    assert js1 == js2
