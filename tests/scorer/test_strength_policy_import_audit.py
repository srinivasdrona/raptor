from __future__ import annotations

import ast
from pathlib import Path

import pytest


MODULE = Path("src/raptor/scorer/strength_policy.py")
FORBIDDEN_MODULES = {
    "raptor.eval",
    "raptor.eval.benchmark",
    "raptor.eval.knowns",
    "raptor.eval.mask_clinvar",
}
FORBIDDEN_PATH_PARTS = {"label", "benchmark", "held-out", "heldout", "clinvar"}


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


def test_strength_policy_module_is_label_blind() -> None:
    if not MODULE.is_file():
        pytest.fail(f"implementation missing: {MODULE}")

    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))

    for imported in _import_names(tree):
        assert not any(
            imported == forbidden or imported.startswith(f"{forbidden}.")
            for forbidden in FORBIDDEN_MODULES
        ), f"{MODULE} imports forbidden module {imported}"

    for literal in _path_literals(tree):
        normalized = literal.lower().replace("\\", "/")
        assert not any(part in normalized for part in FORBIDDEN_PATH_PARTS), (
            f"{MODULE} opens forbidden label-side path {literal!r}"
        )
