from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
RESCUESCREEN_SRC_DIR = REPO_ROOT / "src" / "raptor" / "rescuescreen"
EXPECTED_MODULE_FILES = {"__init__.py", "model.py", "gates.py", "cli.py"}
BASELINE_HEAD = "5919fc091534e04e9cebd1f9e5a3f299aba13e54"

FORBIDDEN_IMPORT_PREFIXES = (
    "subprocess",
    "socket",
    "urllib",
    "urllib3",
    "requests",
    "httpx",
    "aiohttp",
    "grpc",
    "ftplib",
    "telnetlib",
    "smtplib",
    "imaplib",
    "poplib",
    "raptor.atlas",
    "raptor.eval",
    "raptor.packet",
    "raptor.scorer",
    "raptor.rescuescreen.screening",
    "raptor.rescuescreen.docking",
    "raptor.rescuescreen.compound",
    "raptor.rescuescreen.vendor",
    "raptor.rescuescreen.treatment",
    "raptor.rescuescreen.stage",
)

FORBIDDEN_SURFACE_NAME_KEYWORDS = (
    "screening",
    "docking",
    "compound",
    "vendor",
    "treatment",
    "therapy",
    "simulate",
    "simulation",
)

FORBIDDEN_EXECUTION_TOKENS = (
    "autodock",
    "vina",
    "gnina",
    "rdkit",
    "openbabel",
    "schrodinger",
    "chembl",
    "pubchem",
)


def _require_rescuescreen_module_files() -> list[Path]:
    if not RESCUESCREEN_SRC_DIR.is_dir():
        pytest.fail(f"implementation missing: {RESCUESCREEN_SRC_DIR}")

    actual_module_files = {path.name for path in RESCUESCREEN_SRC_DIR.glob("*.py")}
    assert actual_module_files == EXPECTED_MODULE_FILES, (
        "rescuescreen module surface changed: "
        f"expected {sorted(EXPECTED_MODULE_FILES)}, got {sorted(actual_module_files)}"
    )
    return [RESCUESCREEN_SRC_DIR / name for name in sorted(actual_module_files)]


def _import_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _git_diff_is_clean(*pathspecs: str) -> tuple[bool, str]:
    cmd = [
        "git",
        "diff",
        "--exit-code",
        f"{BASELINE_HEAD}..HEAD",
        "--",
        *pathspecs,
    ]
    result = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    output = result.stdout.strip() or result.stderr.strip()
    return (result.returncode == 0, output)


def test_rseg_ac10_expected_rescuescreen_module_surface_exists() -> None:
    _require_rescuescreen_module_files()


def test_rseg_ac10_static_import_firewall_disallows_network_subprocess_and_cross_lane_dependencies() -> None:
    for module_path in _require_rescuescreen_module_files():
        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
        imports = _import_names(tree)

        for imported in imports:
            for forbidden in FORBIDDEN_IMPORT_PREFIXES:
                assert not (imported == forbidden or imported.startswith(f"{forbidden}.")), (
                    f"{module_path} imports forbidden dependency {imported}"
                )

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "os"
            ):
                assert node.func.attr not in {"system", "popen", "spawnl", "spawnlp", "spawnv", "spawnvp"}, (
                    f"{module_path} exposes command execution via os.{node.func.attr}"
                )


def test_rseg_ac11_no_screening_docking_compound_vendor_treatment_execution_surface() -> None:
    module_paths = _require_rescuescreen_module_files()
    for path in module_paths:
        stem = path.stem.lower()
        assert not any(keyword in stem for keyword in FORBIDDEN_SURFACE_NAME_KEYWORDS), (
            f"{path} name leaks forbidden execution surface"
        )

        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name.startswith("_"):
                    continue
                lowered = node.name.lower()
                assert not any(keyword in lowered for keyword in FORBIDDEN_SURFACE_NAME_KEYWORDS), (
                    f"{path} defines forbidden execution-surface symbol {node.name}"
                )

        lowered_source = source.lower()
        assert all(token not in lowered_source for token in FORBIDDEN_EXECUTION_TOKENS), (
            f"{path} contains forbidden execution token"
        )


def test_rseg_ac12_higher_authority_files_are_byte_identical_to_prompt_head() -> None:
    protected_files = (
        "docs/project/specs/rescuescreen-entry-gates-v1.yaml",
        "docs/project/specs/structural-rescue-screen-v1.yaml",
        "docs/project/specs/mechanism-atlas-starter.yaml",
        "docs/DECISIONS.md",
        "docs/PROGRAM.md",
        "docs/project/TODOS.yaml",
        "METHOD.md",
        "README.md",
        "tests/atlas/test_hashing_import_guards.py",
    )
    clean, output = _git_diff_is_clean(*protected_files)
    assert clean, output or "protected authority files were modified"


def test_rseg_ac12_atlas_source_and_data_artifacts_unchanged_since_prompt_head() -> None:
    clean, output = _git_diff_is_clean("src/raptor/atlas", "data")
    assert clean, output or "atlas source or data artifacts were modified"
