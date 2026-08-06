import pytest
import json
import subprocess
import sys
import os
from pathlib import Path


@pytest.mark.requires_reference
def test_ta1_dev_export_blocked_and_deterministic(tmp_path):
    """T-A1 dev export blocked.

    Verify scripts/export_dev_vcf.py:
    1. Uses the real frozen benchmark path and real eval config.
    2. Writes a deterministic JSON status artifact to the specified path when reference/runtime is absent.
    3. The written JSON has status 'BLOCKED_DATA' and lists the four specific missing prerequisites.
    4. Assert dev_n=1104/holdout_n=2577.
    5. No label values/keys in output.
    6. Deterministic bytes on repeat.
    """
    script_path = Path("scripts/export_dev_vcf.py")
    status_output = tmp_path / "tsc_pp3bp4_dev_score_acquisition_2026-07.json"

    # Red validation: fail only for missing implementation
    if not script_path.exists():
        pytest.fail(f"implementation missing: {script_path}")

    from tests.eval.test_path_resolver import require_raptor_data_root
    repo_root = Path(__file__).resolve().parents[2]
    data_root = require_raptor_data_root(repo_root)
    real_benchmark = data_root / "clinvar" / "benchmark" / "benchmark.jsonl"
    if not real_benchmark.exists():
        pytest.fail(f"Missing real frozen benchmark: {real_benchmark}")

    real_eval_config = Path("configs/eval/tsc2.yaml")
    if not real_eval_config.exists():
        pytest.fail(f"Missing real eval config: {real_eval_config}")

    # Run script expecting it to output BLOCKED_DATA with nonexistent reference root
    env = os.environ.copy()
    if "PYTHONPATH" in env:
        del env["PYTHONPATH"] # Set PYTHONPATH to empty/remove it

    cmd = [
        sys.executable,
        str(script_path),
        "--benchmark", str(real_benchmark),
        "--eval-config", str(real_eval_config),
        "--reference-root", "nonexistent/reference/root/path",
        "--benchmark-snapshot", "clinvar_2026-07-07",
        "--out-dir", str(tmp_path / "external-dev-dir"),
        "--status-output", str(status_output),
        "--report-date", "2026-07-18" # Explicit report-date / as-of for deterministic hash
    ]

    res = subprocess.run(cmd, capture_output=True, text=True, env=env)
    
    # Check if the status_output file is written and parse it.
    assert status_output.is_file(), f"Script failed to write status output. Stderr: {res.stderr}\nStdout: {res.stdout}"

    data = json.loads(status_output.read_text(encoding="utf-8"))

    # Verify status is BLOCKED_DATA
    assert data["status"] == "BLOCKED_DATA"

    # Verify n_dev and n_holdout are correct
    assert data["n_dev"] == 1104
    assert data["n_holdout"] == 2577

    # Verify all four missing prerequisites are listed
    missing = data.get("missing_prerequisites", [])
    assert any("reference" in m.lower() or "fasta" in m.lower() for m in missing), "Missing reference root prerequisite"
    assert any("nirvana" in m.lower() or "dbnsfp" in m.lower() or "annotation" in m.lower() for m in missing), "Missing structured REVEL runtime prerequisite"
    assert any("version" in m.lower() for m in missing), "Missing predictor/data version pin prerequisite"
    assert any("license" in m.lower() for m in missing), "Missing license/permitted-use record prerequisite"

    # Verify no labels or keys containing labels are present in any outputs
    output_text = status_output.read_text(encoding="utf-8")
    assert "label" not in output_text.lower()

    # Verify determinism: running twice with same inputs should yield identical JSON (content-hash identical)
    status_output_2 = tmp_path / "tsc_pp3bp4_dev_score_acquisition_2026-07_2.json"
    cmd2 = cmd.copy()
    cmd2[cmd2.index(str(status_output))] = str(status_output_2)
    subprocess.run(cmd2, capture_output=True, text=True, env=env)
    assert status_output_2.is_file()

    # Compare content (bytes must be identical on repeat)
    bytes1 = status_output.read_bytes()
    bytes2 = status_output_2.read_bytes()
    assert bytes1 == bytes2


def test_cli_help_bootstrap_clean_pythonpath():
    """T-A4/T-B8 check all planned scripts run with a clean PYTHONPATH and show help.

    PYTHONPATH must be empty/removed, not 'src'.
    """
    scripts = [
        "scripts/export_dev_vcf.py",
        "scripts/audit_predictor_leakage.py",
        "scripts/build_pp3bp4_transportability_report.py",
        "scripts/build_pp3bp4_revel_mave_concordance.py"
    ]
    for script_name in scripts:
        script_path = Path(script_name)
        if not script_path.exists():
            pytest.fail(f"implementation missing: {script_name}")

        env = os.environ.copy()
        if "PYTHONPATH" in env:
            del env["PYTHONPATH"]

        cmd = [sys.executable, str(script_path), "--help"]
        res = subprocess.run(cmd, capture_output=True, text=True, env=env)
        assert res.returncode == 0, f"CLI help failed under clean PYTHONPATH for {script_name}: {res.stderr}"
        assert "usage" in res.stdout.lower() or "help" in res.stdout.lower()


def test_ta2_stage_a_field_access_regression(tmp_path):
    """Verify that Stage A script uses a pure production seam load_benchmark_variant_ids

    which ignores/does not access label or other non-variant_id fields.
    """
    # 1. Require load_benchmark_variant_ids to exist in scripts/export_dev_vcf
    try:
        from scripts.export_dev_vcf import load_benchmark_variant_ids
    except ImportError as e:
        pytest.fail(f"RED failure: missing production seam load_benchmark_variant_ids in scripts/export_dev_vcf.py: {e}")

    # 2. Write a JSONL with only variant_id (no label/variant_class/source/snapshot)
    only_ids_file = tmp_path / "only_ids.jsonl"
    only_ids_file.write_text(
        json.dumps({"variant_id": "NC_000009.12:10001:A:G"}) + "\n" +
        json.dumps({"variant_id": "NC_000016.10:54321:C:T"}) + "\n"
    )

    # 3. Write a JSONL with same IDs but changed/poison-shaped label and variant_class fields
    poison_file = tmp_path / "poison.jsonl"
    poison_file.write_text(
        json.dumps({"variant_id": "NC_000009.12:10001:A:G", "label": "POISON_LABEL", "variant_class": "POISON_CLASS"}) + "\n" +
        json.dumps({"variant_id": "NC_000016.10:54321:C:T", "label": "POISON_LABEL", "variant_class": "POISON_CLASS"}) + "\n"
    )

    # 4. Both must return identical list of IDs when parsed by load_benchmark_variant_ids
    ids_from_only = load_benchmark_variant_ids(only_ids_file)
    ids_from_poison = load_benchmark_variant_ids(poison_file)

    assert ids_from_only == ["NC_000009.12:10001:A:G", "NC_000016.10:54321:C:T"]
    assert ids_from_only == ids_from_poison

    # 5. Prove label fields are not accessed.
    # We can do this by patching json.loads in scripts.export_dev_vcf to return a proxy dictionary
    # that raises an AssertionError if any key other than "variant_id" is accessed.
    import scripts.export_dev_vcf
    original_loads = scripts.export_dev_vcf.json.loads

    class StrictAccessDict(dict):
        def __getitem__(self, key):
            if key != "variant_id":
                raise AssertionError(f"Security/Privacy violation: Stage-A code accessed non-variant_id key: {key!r}")
            return super().__getitem__(key)
        def get(self, key, default=None):
            if key != "variant_id":
                raise AssertionError(f"Security/Privacy violation: Stage-A code accessed non-variant_id key: {key!r}")
            return super().get(key, default)

    def strict_loads(*args, **kwargs):
        res = original_loads(*args, **kwargs)
        if isinstance(res, dict):
            return StrictAccessDict(res)
        return res

    scripts.export_dev_vcf.json.loads = strict_loads
    try:
        # This call must NOT raise any AssertionError because load_benchmark_variant_ids
        # must not access anything other than "variant_id".
        ids = load_benchmark_variant_ids(poison_file)
        assert ids == ["NC_000009.12:10001:A:G", "NC_000016.10:54321:C:T"]
    finally:
        scripts.export_dev_vcf.json.loads = original_loads
