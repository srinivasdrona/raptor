from __future__ import annotations

import ast
from pathlib import Path

import pytest

MODULES = (
    Path("src/raptor/eval/mask_clinvar.py"),
    Path("scripts/mask_clinvar_source.py"),
)
FORBIDDEN_MODULES = {
    "bias_2015",
    "src.preprocessing",
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

def test_ac_m9_modules_preserve_label_and_agpl_boundaries() -> None:
    for path in MODULES:
        if not path.is_file():
            # Standard exception to get a clean RED for missing module
            raise ImportError(f"implementation missing: {path}")
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
