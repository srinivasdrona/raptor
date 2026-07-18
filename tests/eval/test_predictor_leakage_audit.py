import pytest
import json
import hashlib
import os
import sys
import subprocess
from pathlib import Path


def _sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_td1_leakage_audit_precedence(tmp_path):
    """T-D1 precedence.

    Verify the precedence order: BLOCKED_DATA -> FAIL -> UNKNOWN -> PASS.
    Supply synthetic direct/component manifest files and benchmark IDs, then assert
    the audit computes overlaps/status.
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
    direct_file.write_text("NC_000009.12:12345:A:G\n")
    direct_sha = _sha256_of_file(direct_file)

    component_file = tmp_path / "component.txt"
    component_file.write_text("NC_000016.10:54321:C:T\n")
    component_sha = _sha256_of_file(component_file)

    clean_manifest = tmp_path / "clean.txt"
    clean_manifest.write_text("NC_000009.12:99999:T:C\n")
    clean_sha = _sha256_of_file(clean_manifest)

    registry_file = tmp_path / "registry.json"
    registry_data = {
        "schema": "pp3bp4-manifest-registry/1",
        "direct": {"available": True, "verified": True, "sha256": direct_sha},
        "components": {
            "comp1": {"available": True, "verified": True, "sha256": clean_sha}
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

    # For component fail, update registry to hold the correct hashes
    registry_data_comp = {
        "schema": "pp3bp4-manifest-registry/1",
        "direct": {"available": True, "verified": True, "sha256": clean_sha},
        "components": {
            "comp1": {"available": True, "verified": True, "sha256": component_sha}
        }
    }
    registry_file.write_text(json.dumps(registry_data_comp), encoding="utf-8")

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
        "direct": {"available": True, "verified": True, "sha256": clean_sha},
        "components": {
            "comp1": {"available": False, "verified": False, "sha256": clean_sha}
        }
    }
    bad_registry_file = tmp_path / "bad_registry.json"
    bad_registry_file.write_text(json.dumps(bad_registry_data), encoding="utf-8")

    status_unknown = evaluate_leakage_audit(
        benchmark_path=str(benchmark_file),
        direct_manifest_path=str(clean_manifest),
        component_manifest_paths={"comp1": str(clean_manifest)},
        registry_path=str(bad_registry_file)
    )
    assert status_unknown.status == LeakageStatus.UNKNOWN

    # 4. PASS only when all manifests available/verified/normalized and zero overlap
    registry_data_pass = {
        "schema": "pp3bp4-manifest-registry/1",
        "direct": {"available": True, "verified": True, "sha256": clean_sha},
        "components": {
            "comp1": {"available": True, "verified": True, "sha256": clean_sha}
        }
    }
    registry_file_pass = tmp_path / "registry_pass.json"
    registry_file_pass.write_text(json.dumps(registry_data_pass), encoding="utf-8")

    status_pass = evaluate_leakage_audit(
        benchmark_path=str(benchmark_file),
        direct_manifest_path=str(clean_manifest),
        component_manifest_paths={"comp1": str(clean_manifest)},
        registry_path=str(registry_file_pass)
    )
    assert status_pass.status == LeakageStatus.PASS
    assert status_pass.direct_overlap == 0
    assert status_pass.component_overlap == 0

    # 5. Explicit Mismatch Rejection (actual file hash != registry hash)
    mismatch_registry_data = {
        "schema": "pp3bp4-manifest-registry/1",
        "direct": {"available": True, "verified": True, "sha256": "wronghash" + "a"*55},
        "components": {
            "comp1": {"available": True, "verified": True, "sha256": clean_sha}
        }
    }
    mismatch_registry_file = tmp_path / "mismatch_registry.json"
    mismatch_registry_file.write_text(json.dumps(mismatch_registry_data), encoding="utf-8")

    from raptor.eval.predictor_leakage_audit import LeakageValidationError
    with pytest.raises(LeakageValidationError, match="hash|mismatch|sha256"):
        evaluate_leakage_audit(
            benchmark_path=str(benchmark_file),
            direct_manifest_path=str(clean_manifest),
            component_manifest_paths={"comp1": str(clean_manifest)},
            registry_path=str(mismatch_registry_file)
        )

    # 6. Available required entry in registry but caller doesn't provide path -> BLOCKED_DATA
    registry_data_unsupplied = {
        "schema": "pp3bp4-manifest-registry/1",
        "direct": {"available": True, "verified": True, "sha256": clean_sha},
        "components": {
            "comp1": {"available": True, "verified": True, "sha256": clean_sha},
            "comp_missing_path": {"available": True, "verified": True, "sha256": clean_sha}
        }
    }
    registry_file_unsupplied = tmp_path / "registry_unsupplied.json"
    registry_file_unsupplied.write_text(json.dumps(registry_data_unsupplied), encoding="utf-8")

    status_unsupplied = evaluate_leakage_audit(
        benchmark_path=str(benchmark_file),
        direct_manifest_path=str(clean_manifest),
        component_manifest_paths={"comp1": str(clean_manifest)},
        registry_path=str(registry_file_unsupplied)
    )
    assert status_unsupplied.status == LeakageStatus.BLOCKED_DATA

    # 7. Unavailable required entry in registry with no path -> UNKNOWN
    registry_data_unavail_no_path = {
        "schema": "pp3bp4-manifest-registry/1",
        "direct": {"available": True, "verified": True, "sha256": clean_sha},
        "components": {
            "comp1": {"available": True, "verified": True, "sha256": clean_sha},
            "comp_unavail": {"available": False, "verified": False, "sha256": clean_sha}
        }
    }
    registry_file_unavail_no_path = tmp_path / "registry_unavail_no_path.json"
    registry_file_unavail_no_path.write_text(json.dumps(registry_data_unavail_no_path), encoding="utf-8")

    status_unavail_no_path = evaluate_leakage_audit(
        benchmark_path=str(benchmark_file),
        direct_manifest_path=str(clean_manifest),
        component_manifest_paths={"comp1": str(clean_manifest)},
        registry_path=str(registry_file_unavail_no_path)
    )
    assert status_unavail_no_path.status == LeakageStatus.UNKNOWN


def test_td1_leakage_audit_label_invariance(tmp_path):
    """Verify benchmark labels are ignored and changing them does not change status/hash."""
    from raptor.eval.predictor_leakage_audit import evaluate_leakage_audit

    direct_file = tmp_path / "direct.txt"
    direct_file.write_text("NC_000009.12:99999:T:C\n")
    direct_sha = _sha256_of_file(direct_file)

    registry_file = tmp_path / "registry.json"
    registry_data = {
        "schema": "pp3bp4-manifest-registry/1",
        "direct": {"available": True, "verified": True, "sha256": direct_sha}
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


def test_td2_canonical_ids_and_unnormalizable_rejection(tmp_path):
    """T-D2 canonical IDs and unnormalizable rejection.

    Verify SPDI normalization is applied, unnormalizable variants fail loud or report FAIL.
    """
    from raptor.eval.predictor_leakage_audit import evaluate_leakage_audit

    benchmark_file = tmp_path / "benchmark_unnorm.jsonl"
    benchmark_file.write_text(
        json.dumps({"variant_id": "NC_000009.12:12345:A:G", "label": "P", "variant_class": "missense"}) + "\n" +
        json.dumps({"variant_id": "unnormalizable_id_format", "label": "B", "variant_class": "missense"}) + "\n"
    )

    clean_manifest = tmp_path / "clean.txt"
    clean_manifest.write_text("NC_000009.12:99999:T:C\n")
    clean_sha = _sha256_of_file(clean_manifest)

    registry_file = tmp_path / "registry.json"
    registry_data = {
        "schema": "pp3bp4-manifest-registry/1",
        "direct": {"available": True, "verified": True, "sha256": clean_sha}
    }
    registry_file.write_text(json.dumps(registry_data), encoding="utf-8")

    from raptor.eval.predictor_leakage_audit import LeakageValidationError
    with pytest.raises(LeakageValidationError):
        evaluate_leakage_audit(
            benchmark_path=str(benchmark_file),
            direct_manifest_path=str(clean_manifest),
            registry_path=str(registry_file),
            force_normalization=True
        )


def test_cli_help_bootstrap():
    """T-A4/T-B8 check script can run with a clean PYTHONPATH and shows help."""
    script_path = Path("scripts/audit_predictor_leakage.py")
    if not script_path.exists():
        pytest.fail(f"implementation missing: {script_path}")

    env = os.environ.copy()
    if "PYTHONPATH" in env:
        del env["PYTHONPATH"]

    cmd = [sys.executable, str(script_path), "--help"]
    res = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert res.returncode == 0, f"CLI help failed under clean PYTHONPATH: {res.stderr}"
    assert "usage" in res.stdout.lower() or "help" in res.stdout.lower()

