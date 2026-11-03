from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "raptor"
SOURCEOPS_ROOT = SRC_ROOT / "sourceops"
REGISTRY_PATH = REPO_ROOT / "configs" / "sourceops" / "source_registry.yaml"
FORBIDDEN_DOMAIN_IMPORT_PREFIXES = (
    "raptor.scorer",
    "raptor.eval",
    "raptor.packet",
    "raptor.census",
    "raptor.atlas",
    "raptor.ingest",
    "raptor.kb",
    "raptor.external",
)
FORBIDDEN_NETWORK_IMPORTS = {
    "socket",
    "http",
    "http.client",
    "urllib.request",
    "urllib3",
    "requests",
    "httpx",
    "aiohttp",
    "ftplib",
    "paramiko",
    "websockets",
}
EXTERNAL_SCHEME_RE = re.compile(r"(https?://|s3://|gs://|azure://|ftp://|file://)", flags=re.IGNORECASE)
ABSOLUTE_PATH_RE = re.compile(r"^([a-zA-Z]:\\|/)")


def _iter_python_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def _module_imports(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level and (node.module is None or node.module.startswith("sourceops")):
                continue
            if node.module:
                imports.append((node.module, node.lineno))
    return imports


def _canonical_registry_hash(payload: dict[str, Any]) -> str:
    basis = copy.deepcopy(payload)
    basis.pop("registry_content_hash", None)
    canonical = json.dumps(
        basis,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    src_path = str(REPO_ROOT / "src")
    env["PYTHONPATH"] = f"{src_path}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    return subprocess.run(
        [sys.executable, "-m", "raptor.sourceops.cli", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
    )


def _run_validate(registry_path: Path) -> subprocess.CompletedProcess[str]:
    return _run_cli("validate", "--registry", str(registry_path))


def _parse_json(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    if not result.stdout.strip():
        pytest.fail(
            "CLI stdout must contain JSON.\n"
            f"returncode={result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        pytest.fail("CLI JSON payload must be a top-level object")
    return payload


def _error_codes(report: dict[str, Any]) -> set[str]:
    codes: set[str] = set()
    if isinstance(report.get("errors"), list):
        for err in report["errors"]:
            if isinstance(err, dict) and isinstance(err.get("code"), str):
                codes.add(err["code"])
    if isinstance(report.get("error"), dict) and isinstance(report["error"].get("code"), str):
        codes.add(report["error"]["code"])
    for key in ("code", "error_code", "failure_code"):
        value = report.get(key)
        if isinstance(value, str):
            codes.add(value)
    return {code for code in codes if code}


def test_ac09_no_existing_package_imports_sourceops() -> None:
    offenders: list[str] = []
    for py_path in _iter_python_files(SRC_ROOT):
        if py_path.is_relative_to(SOURCEOPS_ROOT):
            continue
        for imported, lineno in _module_imports(py_path):
            if imported == "raptor.sourceops" or imported.startswith("raptor.sourceops."):
                offenders.append(f"{py_path.relative_to(REPO_ROOT)}:{lineno}:{imported}")
    assert not offenders, "existing RAPTOR packages must not import sourceops in V2-S1:\n" + "\n".join(offenders)


def test_ac09_sourceops_dependency_and_network_boundaries() -> None:
    if not SOURCEOPS_ROOT.exists():
        pytest.fail(f"SourceOps package is not implemented: {SOURCEOPS_ROOT}")
    files = _iter_python_files(SOURCEOPS_ROOT)
    assert files, "SourceOps package must contain Python modules"

    forbidden_imports: list[str] = []
    disallowed_third_party: list[str] = []
    stdlib_modules = set(sys.stdlib_module_names)

    for py_path in files:
        for imported, lineno in _module_imports(py_path):
            if imported.startswith("raptor.") and not imported.startswith("raptor.sourceops"):
                if imported.startswith(FORBIDDEN_DOMAIN_IMPORT_PREFIXES):
                    forbidden_imports.append(f"{py_path.relative_to(REPO_ROOT)}:{lineno}:{imported}")
                else:
                    forbidden_imports.append(f"{py_path.relative_to(REPO_ROOT)}:{lineno}:{imported}")
                continue

            if imported in FORBIDDEN_NETWORK_IMPORTS:
                forbidden_imports.append(f"{py_path.relative_to(REPO_ROOT)}:{lineno}:{imported}")
                continue
            if imported == "urllib":
                forbidden_imports.append(f"{py_path.relative_to(REPO_ROOT)}:{lineno}:urllib")
                continue

            top = imported.split(".")[0]
            if top in {"yaml"}:
                continue
            if top in {"raptor"}:
                continue
            if top in stdlib_modules and imported not in FORBIDDEN_NETWORK_IMPORTS:
                continue
            disallowed_third_party.append(f"{py_path.relative_to(REPO_ROOT)}:{lineno}:{imported}")

    assert not forbidden_imports, "SourceOps must not import network clients or RAPTOR domain packages:\n" + "\n".join(
        forbidden_imports
    )
    assert not disallowed_third_party, "SourceOps must use only stdlib + PyYAML dependencies:\n" + "\n".join(
        disallowed_third_party
    )


def test_ac09_static_external_content_dereference_calls_are_forbidden() -> None:
    if not SOURCEOPS_ROOT.exists():
        pytest.fail(f"SourceOps package is not implemented: {SOURCEOPS_ROOT}")

    offenders: list[str] = []
    for py_path in _iter_python_files(SOURCEOPS_ROOT):
        tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                call_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                call_name = node.func.attr
            else:  # pragma: no cover - defensive
                continue
            if call_name not in {"open", "read_text", "read_bytes"}:
                continue
            if not node.args:
                continue
            first_arg = node.args[0]
            if not isinstance(first_arg, ast.Constant) or not isinstance(first_arg.value, str):
                continue
            value = first_arg.value.strip()
            if EXTERNAL_SCHEME_RE.search(value) or ABSOLUTE_PATH_RE.match(value):
                offenders.append(f"{py_path.relative_to(REPO_ROOT)}:{node.lineno}:{call_name}:{value}")
    assert not offenders, "SourceOps contains static external-content dereference calls:\n" + "\n".join(offenders)


def test_ac09_no_external_content_dereference_probe(tmp_path: Path) -> None:
    if not REGISTRY_PATH.exists():
        pytest.fail(f"SourceOps registry file is not implemented: {REGISTRY_PATH}")
    payload = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        pytest.fail("source_registry.yaml must parse into a mapping")

    records = payload.get("source_records")
    if not isinstance(records, list):
        pytest.fail("source_records must be a list")
    target_ref = None
    for record in records:
        if not isinstance(record, dict):
            continue
        refs = record.get("declaration_refs")
        if isinstance(refs, list) and refs and isinstance(refs[0], dict):
            target_ref = refs[0]
            break
    if target_ref is None:
        pytest.fail("Expected at least one declaration reference for external-read probe")

    target_ref["path"] = "https://example.invalid/source_registry/declaration.yaml"
    payload["registry_content_hash"] = _canonical_registry_hash(payload)
    probe = tmp_path / "external_read_probe.yaml"
    _write_yaml(probe, payload)

    result = _run_validate(probe)
    assert result.returncode == 2, result.stderr or result.stdout
    report = _parse_json(result)
    assert _error_codes(report).intersection(
        {"DECLARATION_REFERENCE_INVALID", "NETWORK_OR_EXTERNAL_READ_ATTEMPT"}
    ), report


def test_ac09_catalog_external_content_root_dereference_is_rejected(tmp_path: Path) -> None:
    if not REGISTRY_PATH.exists():
        pytest.fail(f"SourceOps registry file is not implemented: {REGISTRY_PATH}")
    payload = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        pytest.fail("source_registry.yaml must parse into a mapping")

    records = payload.get("source_records")
    if not isinstance(records, list):
        pytest.fail("source_records must be a list")

    catalog_ref = None
    for record in records:
        if not isinstance(record, dict):
            continue
        refs = record.get("declaration_refs")
        if not isinstance(refs, list):
            continue
        for ref in refs:
            if (
                isinstance(ref, dict)
                and isinstance(ref.get("path"), str)
                and ref["path"].replace("\\", "/") == "configs/atlas/catalogs/tsc2/catalog.yaml"
            ):
                catalog_ref = ref
                break
        if catalog_ref is not None:
            break

    if catalog_ref is None:
        pytest.fail("Expected atlas catalog declaration reference in source registry")

    catalog_ref["path"] = "file:///D:/external-content-root/catalog.yaml"
    payload["registry_content_hash"] = _canonical_registry_hash(payload)
    probe = tmp_path / "catalog_external_root_probe.yaml"
    _write_yaml(probe, payload)

    result = _run_validate(probe)
    assert result.returncode == 2, result.stderr or result.stdout
    report = _parse_json(result)
    assert _error_codes(report).intersection(
        {"DECLARATION_REFERENCE_INVALID", "NETWORK_OR_EXTERNAL_READ_ATTEMPT"}
    ), report
