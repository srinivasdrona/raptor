"""Label/import audit for track `strength-policy-2026-07`'s new modules --
mirrors `tests/eval/test_bias_lineage_forbidden_import_audit.py`'s AC-L12
style audit. `strength_policy.py`/`strength_materiality.py`/the probe CLI
must never import a label/benchmark module or BIAS itself (ADR-0007), and
must never open a path that looks like a label/held-out file.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

MODULES = (
    Path("src/raptor/scorer/strength_policy.py"),
    Path("src/raptor/scorer/strength_materiality.py"),
    Path("scripts/run_strength_materiality_probe.py"),
)
FORBIDDEN_MODULES = {
    "raptor.eval.knowns",
    "raptor.eval.benchmark",
    "bias_2015",
}
FORBIDDEN_PATH_PARTS = {"labels", "benchmark", "held-out", "heldout"}


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


def test_strength_policy_modules_preserve_label_and_agpl_boundaries() -> None:
    for path in MODULES:
        if not path.is_file():
            pytest.fail(f"implementation missing: {path}")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        for imported in _import_names(tree):
            assert not any(
                imported == forbidden or imported.startswith(f"{forbidden}.")
                for forbidden in FORBIDDEN_MODULES
            ), f"{path} imports forbidden module {imported}"

        for literal in _path_literals(tree):
            normalized = literal.lower().replace("\\", "/")
            assert not any(part in normalized for part in FORBIDDEN_PATH_PARTS), (
                f"{path} opens forbidden label-side path {literal!r}"
            )


def test_strength_policy_configs_never_carry_a_truth_sentinel() -> None:
    sentinel = "RAPTOR_HELDOUT_TRUTH_SENTINEL_6D217D"
    files = (
        *MODULES,
        Path("configs/eval/bias_strength_ladder.yaml"),
        Path("configs/acmg/strength_policy.yaml"),
    )
    for path in files:
        if not path.is_file():
            pytest.fail(f"implementation missing: {path}")
        assert sentinel not in path.read_text(encoding="utf-8")


def test_strength_materiality_never_reads_clinvar_significance_field() -> None:
    """The probe must select nothing based on `acmgClassification`/ClinVar
    significance -- confirm the source never actually ACCESSES that
    `BiasRecord` field (mentioning it in a docstring/comment, to disclaim
    it, is fine and expected)."""
    path = Path("src/raptor/scorer/strength_materiality.py")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    accessed_attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "acmg_classification" not in accessed_attrs
