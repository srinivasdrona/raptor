import pytest
import json
import hashlib
import os
import sys
import subprocess
from pathlib import Path


def test_td1_leakage_audit_precedence(tmp_path):
    """T-D1 precedence.

    Verify the precedence order: BLOCKED_DATA -> FAIL -> UNKNOWN -> PASS.
    Supply synthetic direct/component manifest files and benchmark IDs, then assert
    the audit computes overlaps/status. (Correction 7)
    """
    from raptor.eval.predictor_leakage_audit import evaluate_leakage_audit, LeakageStatus

    # Check status values are distinct
    assert LeakageStatus.BLOCKED_DATA != LeakageStatus.FAIL
    assert LeakageStatus.FAIL != LeakageStatus.UNKNOWN
    assert LeakageStatus.UNKNOWN != LeakageStatus.PASS

    benchmark_file = tmp_path / "benchmark.jsonl"
    benchmark_file.write_text(
        json.dumps({"variant_id": "NC_000009.12:12345:A:G", "label": "P", "variant_class": "missense"}) + "\n" +
        json.dumps({"variant_id": "NC_000016.10:54321:C:T", "label": "B", "variant_class": "missense"}) + "\n"
    )

    # 1. BLOCKED_DATA if required benchmark or input cannot be read/validated (unreadable registry/benchmark)
    status_blocked = evaluate_leakage_audit(
        benchmark_path="nonexistent_benchmark.jsonl",
        direct_manifest_path=None,
        component_manifest_paths=None,
        registry_path=None
    )
    assert status_blocked.status == LeakageStatus.BLOCKED_DATA

    # Create dummy direct and component manifest files
    direct_file = tmp_path / "direct.txt"
    direct_file.write_text("NC_000009.12:12345:A:G\n") # overlap with benchmark!

    component_file = tmp_path / "component.txt"
    component_file.write_text("NC_000016.10:54321:C:T\n") # overlap with benchmark!

    clean_manifest = tmp_path / "clean.txt"
    clean_manifest.write_text("NC_000009.12:99999:T:C\n") # no overlap

    registry_file = tmp_path / "registry.json"
    registry_data = {
        "schema": "pp3bp4-manifest-registry/1",
        "direct": {"available": True, "verified": True, "sha256": "placeholder"},
        "components": {
            "comp1": {"available": True, "verified": True, "sha256": "placeholder"}
        }
    }
    registry_file.write_text(json.dumps(registry_data), encoding="utf-8")

    # 2. FAIL if actual overlap found (direct or component)
    status_fail_direct = evaluate_leakage_audit(
        benchmark_path=str(benchmark_file),
        direct_manifest_path=str(direct_file),
        component_manifest_paths={"comp1": str(clean_manifest)},
        registry_path=str(registry_file)
    )
    assert status_fail_direct.status == LeakageStatus.FAIL
    assert status_fail_direct.direct_overlap > 0

    status_fail_component = evaluate_leakage_audit(
        benchmark_path=str(benchmark_file),
        direct_manifest_path=str(clean_manifest),
        component_manifest_paths={"comp1": str(component_file)},
        registry_path=str(registry_file)
    )
    assert status_fail_component.status == LeakageStatus.FAIL
    assert status_fail_component.component_overlap > 0

    # 3. UNKNOWN if no verified overlap found, but any required component/direct manifest is unavailable/unverified
    bad_registry_data = {
        "schema": "pp3bp4-manifest-registry/1",
        "direct": {"available": True, "verified": True, "sha256": "placeholder"},
        "components": {
            "comp1": {"available": False, "verified": False, "sha256": "placeholder"}
        }
    }
    bad_registry_file = tmp_path / "bad_registry.json"
    bad_registry_file.write_text(json.dumps(bad_registry_data), encoding="utf-8")

    status_unknown = evaluate_leakage_audit(
        benchmark_path=str(benchmark_file),
        direct_manifest_path=str(clean_manifest),
        component_manifest_paths={"comp1": str(clean_manifest)}, # clean, but marked unverified in registry!
        registry_path=str(bad_registry_file)
    )
    assert status_unknown.status == LeakageStatus.UNKNOWN

    # 4. PASS only when all manifests available/verified/normalized and zero overlap
    status_pass = evaluate_leakage_audit(
        benchmark_path=str(benchmark_file),
        direct_manifest_path=str(clean_manifest),
        component_manifest_paths={"comp1": str(clean_manifest)},
        registry_path=str(registry_file)
    )
    assert status_pass.status == LeakageStatus.PASS
    assert status_pass.direct_overlap == 0
    assert status_pass.component_overlap == 0


def test_td1_leakage_audit_label_invariance(tmp_path):
    """Verify benchmark labels are ignored and changing them does not change status/hash."""
    from raptor.eval.predictor_leakage_audit import evaluate_leakage_audit, LeakageStatus

    direct_file = tmp_path / "direct.txt"
    direct_file.write_text("NC_000009.12:99999:T:C\n")

    registry_file = tmp_path / "registry.json"
    registry_data = {
        "schema": "pp3bp4-manifest-registry/1",
        "direct": {"available": True, "verified": True, "sha256": "placeholder"}
    }
    registry_file.write_text(json.dumps(registry_data), encoding="utf-8")

    bench_1 = tmp_path / "bench1.jsonl"
    bench_1.write_text(json.dumps({"variant_id": "NC_000009.12:12345:A:G", "label": "P", "variant_class": "missense"}) + "\n")

    bench_2 = tmp_path / "bench2.jsonl"
    bench_2.write_text(json.dumps({"variant_id": "NC_000009.12:12345:A:G", "label": "B", "variant_class": "missense"}) + "\n") # label changed!

    report1 = evaluate_leakage_audit(
        benchmark_path=str(bench_1),
        direct_manifest_path=str(direct_file),
        registry_path=str(registry_file)
    )
    report2 = evaluate_leakage_audit(
        benchmark_path=str(bench_2),
        direct_manifest_path=str(direct_file),
        registry_path=str(registry_file)
    )

    assert report1.status == report2.status
    assert report1.content_hash == report2.content_hash


def test_td2_canonical_ids_and_exclusion(tmp_path):
    """T-D2 canonical IDs and exclusion.

    Verify SPDI normalization is applied, unnormalizable variants fail loud or report FAIL.
    Verify explicit NTHL1 exclusion: assert a TSC2 row on NC_000016.10 is retained while
    an explicitly annotated NTHL1 row is excluded. Never infer NTHL1 from accession. (Correction 4)
    """
    from raptor.eval.predictor_leakage_audit import evaluate_leakage_audit, LeakageStatus

    # Unnormalizable variant must fail loud or report FAIL, never PASS
    benchmark_file = tmp_path / "benchmark_unnorm.jsonl"
    benchmark_file.write_text(
        json.dumps({"variant_id": "NC_000009.12:12345:A:G", "label": "P", "variant_class": "missense"}) + "\n" +
        json.dumps({"variant_id": "unnormalizable_id_format", "label": "B", "variant_class": "missense"}) + "\n"
    )

    clean_manifest = tmp_path / "clean.txt"
    clean_manifest.write_text("NC_000009.12:99999:T:C\n")

    registry_file = tmp_path / "registry.json"
    registry_data = {
        "schema": "pp3bp4-manifest-registry/1",
        "direct": {"available": True, "verified": True, "sha256": "placeholder"}
    }
    registry_file.write_text(json.dumps(registry_data), encoding="utf-8")

    with pytest.raises(Exception):
        evaluate_leakage_audit(
            benchmark_path=str(benchmark_file),
            direct_manifest_path=str(clean_manifest),
            registry_path=str(registry_file),
            force_normalization=True
        )

    # NTHL1 exclusion check (Correction 4):
    # Benchmark containing both a TSC2 row and an explicitly annotated NTHL1 row on NC_000016.10
    # TSC2 is retained, NTHL1 is excluded.
    benchmark_file_nthl1 = tmp_path / "benchmark_nthl1.jsonl"
    # Row 1: TSC2 on NC_000016.10
    # Row 2: NTHL1 explicitly annotated
    benchmark_file_nthl1.write_text(
        json.dumps({"variant_id": "NC_000016.10:12345:A:G", "label": "P", "variant_class": "missense", "gene": "TSC2"}) + "\n" +
        json.dumps({"variant_id": "NC_000016.10:23456:C:T", "label": "B", "variant_class": "missense", "gene": "NTHL1"}) + "\n"
    )

    # If the manifest contains NC_000016.10:12345:A:G, audit should FAIL because of TSC2 overlap.
    manifest_tsc2_overlap = tmp_path / "manifest_tsc2.txt"
    manifest_tsc2_overlap.write_text("NC_000016.10:12345:A:G\n")

    report_tsc2 = evaluate_leakage_audit(
        benchmark_path=str(benchmark_file_nthl1),
        direct_manifest_path=str(manifest_tsc2_overlap),
        registry_path=str(registry_file)
    )
    assert report_tsc2.status == LeakageStatus.FAIL # TSC2 overlap correctly detected

    # If the manifest contains NC_000016.10:23456:C:T (NTHL1), audit should PASS because NTHL1 is excluded.
    manifest_nthl1_overlap = tmp_path / "manifest_nthl1.txt"
    manifest_nthl1_overlap.write_text("NC_000016.10:23456:C:T\n")

    report_nthl1 = evaluate_leakage_audit(
        benchmark_path=str(benchmark_file_nthl1),
        direct_manifest_path=str(manifest_nthl1_overlap),
        registry_path=str(registry_file)
    )
    assert report_nthl1.status == LeakageStatus.PASS # NTHL1 overlap ignored!


def test_cli_help_bootstrap():
    """T-A4/T-B8 check script can run with a clean PYTHONPATH and shows help."""
    script_path = Path("scripts/audit_predictor_leakage.py")
    if not script_path.exists():
        pytest.skip("audit_predictor_leakage.py not implemented yet")

    env = os.environ.copy()
    env["PYTHONPATH"] = "src"

    cmd = [sys.executable, str(script_path), "--help"]
    res = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert res.returncode == 0, f"CLI help failed under clean PYTHONPATH: {res.stderr}"
    assert "usage" in res.stdout.lower() or "help" in res.stdout.lower()

