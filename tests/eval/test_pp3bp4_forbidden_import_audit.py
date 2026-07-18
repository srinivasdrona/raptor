from __future__ import annotations

import ast
import os
from pathlib import Path
import pytest


# List of shadow modules/scripts that we audit for forbidden access
SHADOW_FILES = {
    "policy_classifier": Path("src/raptor/eval/pp3bp4_candidate_policy.py"),
    "score_table": Path("src/raptor/eval/pp3bp4_score_table.py"),
    "leakage_audit": Path("src/raptor/eval/predictor_leakage_audit.py"),
    "transportability": Path("src/raptor/eval/pp3bp4_transportability.py"),
    "export_dev_vcf": Path("scripts/export_dev_vcf.py"),
    "transportability_cli": Path("scripts/build_pp3bp4_transportability_report.py"),
    "leakage_cli": Path("scripts/audit_predictor_leakage.py"),
    "mave_cli": Path("scripts/build_pp3bp4_revel_mave_concordance.py"),
}


def _import_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _path_literals(tree: ast.AST) -> list[str]:
    values: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function_name = ""
        if isinstance(node.func, ast.Name):
            function_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            function_name = node.func.attr
        if function_name not in {"open", "Path", "read_text", "read_bytes"}:
            continue
        for argument in node.args:
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                values.append(argument.value)
    return values


def _defined_function_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            names.add(node.name)
    return names


def test_tc1_policy_classifier_imports() -> None:
    """Policy classifier cannot import scorer/harness/gate/combine/metrics/benchmark/live_source/terminal_source/bias_2015

    and cannot define get_evidence.
    """
    path = SHADOW_FILES["policy_classifier"]
    if not path.is_file():
        pytest.fail(f"implementation missing: {path}")

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported_modules = _import_names(tree)

    forbidden = {
        "raptor.scorer", "raptor.eval.harness", "raptor.eval.gate",
        "raptor.eval.combine", "raptor.eval.metrics", "raptor.eval.benchmark",
        "raptor.eval.live_source", "raptor.eval.terminal_source", "bias_2015",
    }
    
    for imp in imported_modules:
        assert not any(
            imp == f or imp.startswith(f"{f}.") for f in forbidden
        ), f"Policy classifier imports forbidden module {imp}"

    # Cannot define get_evidence
    funcs = _defined_function_names(tree)
    assert "get_evidence" not in funcs, f"Policy classifier must not define get_evidence"

    # Opens only policy JSON (no labels/benchmark/held-out)
    for literal in _path_literals(tree):
        normalized = literal.lower().replace("\\", "/")
        assert not any(part in normalized for part in ["labels", "benchmark", "heldout", "held-out", "scores"]), (
            f"Policy classifier opens forbidden path literal {literal!r}"
        )


def test_tc1_leakage_audit_imports() -> None:
    """Leakage audit reads benchmark variant_id only, never labels or held-out values."""
    path = SHADOW_FILES["leakage_audit"]
    if not path.is_file():
        pytest.fail(f"implementation missing: {path}")

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for literal in _path_literals(tree):
        normalized = literal.lower().replace("\\", "/")
        # Leakage audit can read benchmark (for variant_ids) but not labels or held-out
        assert "labels" not in normalized, f"Leakage audit opens forbidden path with labels: {literal!r}"
        assert "heldout" not in normalized and "held-out" not in normalized, (
            f"Leakage audit opens forbidden path with held-out: {literal!r}"
        )


def test_tc1_stage_a_imports() -> None:
    """Stage A (export_dev_vcf and score table) opens dev IDs and score table only, never any label."""
    for key in ["score_table", "export_dev_vcf"]:
        path = SHADOW_FILES[key]
        if not path.is_file():
            pytest.fail(f"implementation missing: {path}")

        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported_modules = _import_names(tree)
        for literal in _path_literals(tree):
            normalized = literal.lower().replace("\\", "/")
            assert "labels" not in normalized, f"{key} opens forbidden path with labels: {literal!r}"


def test_tc1_stage_b_imports() -> None:
    """Stage B may read dev labels only after attestation and must reject held-out IDs."""
    path = SHADOW_FILES["transportability"]
    if not path.is_file():
        pytest.fail(f"implementation missing: {path}")

    # Inspect the source code of transportability to verify it performs attestation check
    source_code = path.read_text(encoding="utf-8")
    assert "attestation" in source_code or "ScoreTableAttestation" in source_code
    # Must reject held-out IDs
    assert "holdout" in source_code or "heldout" in source_code or "held_out" in source_code


def test_tc1_production_modules_do_not_import_shadow() -> None:
    """No production module or runner imports the new shadow modules.

    Scan ALL existing src/raptor/**/*.py and relevant existing runner scripts,
    excluding only the new shadow modules/scripts themselves. Do not omit src/raptor/eval. (Correction 9)
    """
    repo_root = Path(__file__).parent.parent.parent
    src_dir = repo_root / "src" / "raptor"
    scripts_dir = repo_root / "scripts"
    
    forbidden_imports = {
        "raptor.eval.pp3bp4_candidate_policy",
        "raptor.eval.pp3bp4_score_table",
        "raptor.eval.pp3bp4_transportability",
        "raptor.eval.predictor_leakage_audit",
        "raptor.external.mave.revel_concordance",
        "scripts.export_dev_vcf",
        "scripts.build_pp3bp4_transportability_report",
        "scripts.audit_predictor_leakage",
        "scripts.build_pp3bp4_revel_mave_concordance",
    }

    # Shadow modules to exclude
    shadow_module_paths = {
        src_dir / "eval" / "pp3bp4_candidate_policy.py",
        src_dir / "eval" / "pp3bp4_score_table.py",
        src_dir / "eval" / "pp3bp4_transportability.py",
        src_dir / "eval" / "predictor_leakage_audit.py",
    }

    # Shadow scripts to exclude
    shadow_script_paths = {
        scripts_dir / "export_dev_vcf.py",
        scripts_dir / "build_pp3bp4_transportability_report.py",
        scripts_dir / "audit_predictor_leakage.py",
        scripts_dir / "build_pp3bp4_revel_mave_concordance.py",
    }

    # 1. Scan ALL src/raptor/**/*.py (do not omit raptor/eval)
    for root, _, files in os.walk(src_dir):
        for file in files:
            if file.endswith(".py"):
                path = Path(root) / file
                # Skip the shadow modules themselves
                if any(path.resolve() == shadow.resolve() for shadow in shadow_module_paths):
                    continue
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                imported_modules = _import_names(tree)
                for imp in imported_modules:
                    for forbidden in forbidden_imports:
                        assert not (imp == forbidden or imp.startswith(forbidden + ".")), f"Production module {path} imports forbidden shadow module {imp}"

    # 2. Scan scripts/**/*.py (relevant runner scripts)
    if scripts_dir.exists():
        for root, _, files in os.walk(scripts_dir):
            for file in files:
                if file.endswith(".py"):
                    path = Path(root) / file
                    # Skip the shadow scripts themselves
                    if any(path.resolve() == shadow.resolve() for shadow in shadow_script_paths):
                        continue
                    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                    imported_modules = _import_names(tree)
                    for imp in imported_modules:
                        for forbidden in forbidden_imports:
                            assert not (imp == forbidden or imp.startswith(forbidden + ".")), f"Runner script {path} imports forbidden shadow module {imp}"

