"""Static AST-based module-boundary guards and classification-leakage scans.

Two independent static checks enforce the Mechanism Atlas module boundary
in both directions, without relying on ``sys.modules`` introspection:

* :func:`assert_atlas_import_boundary` -- parses every ``.py`` file under
  the atlas package and fails if it imports any forbidden consumer
  package (``raptor.packet``, ``raptor.scorer``, ``raptor.eval``) or any
  Discovery SDK-shaped module.
* :func:`assert_no_consumer_import` -- parses every ``.py`` file under the
  forbidden consumer packages and fails if any of them imports the atlas
  package.

:func:`scan_for_classification_leakage` is a reusable recursive scanner
used by candidate promotion to reject any classifier score or ClinVar/ACMG
classification criterion masquerading as mechanistic evidence.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from raptor.atlas.model import AtlasLeakageError

FORBIDDEN_ATLAS_IMPORT_PREFIXES = ("raptor.packet", "raptor.scorer", "raptor.eval", "discovery")
FORBIDDEN_CONSUMER_MODULES = ("raptor.packet", "raptor.scorer", "raptor.eval")
ATLAS_MODULE_PREFIX = "raptor.atlas"

FORBIDDEN_LEAKAGE_KEYS = frozenset({"classifier_score", "clinvar_derived_criterion"})
FORBIDDEN_ACMG_CRITERIA = frozenset({"PP3", "BP4", "PP5", "BP6", "PS4", "PS3", "BS3"})


def _raptor_src_root() -> Path:
    # guards.py lives at <repo>/src/raptor/atlas/guards.py
    return Path(__file__).resolve().parent.parent


def _resolve_scan_root(package_path: str) -> Path:
    candidate = Path(package_path)
    if candidate.exists():
        return candidate
    # Fall back to a path relative to the repo root inferred from this file,
    # in case tests are invoked from a working directory other than the
    # repository root.
    repo_root = _raptor_src_root().parent.parent
    fallback = repo_root / package_path
    return fallback


def _iter_imported_module_names(py_file: Path):
    source = py_file.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(py_file))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                yield node.module


def _matches_forbidden_prefix(module_name: str, prefixes: tuple[str, ...]) -> str | None:
    for prefix in prefixes:
        if module_name == prefix or module_name.startswith(prefix + "."):
            return prefix
    return None


def assert_atlas_import_boundary(package_path: str = "src/raptor/atlas") -> None:
    """Fail if any module under ``package_path`` imports a forbidden
    consumer package or a Discovery SDK-shaped module."""

    root = _resolve_scan_root(package_path)
    py_files = list(root.glob("**/*.py"))
    if not py_files:
        raise AtlasLeakageError(f"no Python files found under atlas scan root {package_path!r}")

    violations = []
    for py_file in py_files:
        for module_name in _iter_imported_module_names(py_file):
            hit = _matches_forbidden_prefix(module_name, FORBIDDEN_ATLAS_IMPORT_PREFIXES)
            if hit is not None:
                violations.append(f"{py_file}: imports forbidden module {module_name!r} (prefix {hit!r})")

    if violations:
        raise AtlasLeakageError(
            "atlas import boundary violated:\n" + "\n".join(violations)
        )


def assert_no_consumer_import(target: str = "raptor.atlas") -> None:
    """Fail if any forbidden consumer package (packet/scorer/eval) imports
    ``target`` (the atlas package)."""

    raptor_root = _raptor_src_root()
    violations = []

    for consumer in FORBIDDEN_CONSUMER_MODULES:
        remainder = consumer[len("raptor."):]
        parts = remainder.split(".")
        consumer_dir = raptor_root.joinpath(*parts)
        consumer_file = raptor_root.joinpath(*parts[:-1], parts[-1] + ".py")

        scan_targets = []
        if consumer_dir.is_dir():
            scan_targets.extend(consumer_dir.glob("**/*.py"))
        if consumer_file.is_file():
            scan_targets.append(consumer_file)

        for py_file in scan_targets:
            for module_name in _iter_imported_module_names(py_file):
                if module_name == target or module_name.startswith(target + "."):
                    violations.append(f"{py_file}: imports forbidden atlas module {module_name!r}")

    if violations:
        raise AtlasLeakageError(
            "consumer import boundary violated:\n" + "\n".join(violations)
        )


def scan_for_classification_leakage(obj: Any, *, _path: str = "root") -> None:
    """Recursively scan ``obj`` (nested dict/list/tuple/str) for
    classifier-score keys, ClinVar-derived-criterion keys, or bare ACMG
    classification criterion tokens masquerading as mechanistic evidence.
    Raises :class:`AtlasLeakageError` fail-closed on any match."""

    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(key, str) and (key in FORBIDDEN_LEAKAGE_KEYS or key in FORBIDDEN_ACMG_CRITERIA):
                raise AtlasLeakageError(
                    f"classification leakage detected: forbidden key {key!r} at {_path}"
                )
            scan_for_classification_leakage(value, _path=f"{_path}.{key}")
    elif isinstance(obj, (list, tuple, set)):
        for index, item in enumerate(obj):
            scan_for_classification_leakage(item, _path=f"{_path}[{index}]")
    elif isinstance(obj, str):
        if obj in FORBIDDEN_ACMG_CRITERIA:
            raise AtlasLeakageError(
                f"classification leakage detected: forbidden ACMG criterion value {obj!r} at {_path}"
            )
