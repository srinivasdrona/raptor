from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from raptor.sourceops.registry import VALIDATION_CEILING, VALIDATION_SCHEMA_ID, load_registry, status_for_consumer, validate_registry


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _typed_error_entry(exc: Exception, *, fallback_code: str = "REGISTRY_SCHEMA_ERROR") -> dict[str, Any]:
    error_code = getattr(exc, "code", None)
    if not isinstance(error_code, str) or not error_code:
        error_code = fallback_code
    error_type = exc.__class__.__name__
    message = str(exc) or f"{error_type} raised"
    return {"code": error_code, "message": message, "type": error_type}


def _validate(path: str | os.PathLike[str]) -> tuple[int, dict[str, Any]]:
    try:
        payload = load_registry(path)
    except Exception as exc:
        report = {"schema": VALIDATION_SCHEMA_ID, "registry_valid": False, "validation_ceiling": VALIDATION_CEILING, "errors": [_typed_error_entry(exc)]}
        return 2, report
    try:
        result = validate_registry(payload, repo_root=_repo_root())
    except Exception as exc:
        report = {"schema": VALIDATION_SCHEMA_ID, "registry_valid": False, "validation_ceiling": VALIDATION_CEILING, "errors": [_typed_error_entry(exc)]}
        return 2, report
    report = result.as_report()
    report["schema"] = VALIDATION_SCHEMA_ID
    report["validation_ceiling"] = VALIDATION_CEILING
    return (0, report) if result.registry_valid else (2, report)


def _status(path: str | os.PathLike[str], consumer_id: str) -> tuple[int, dict[str, Any]]:
    try:
        payload = load_registry(path)
    except Exception as exc:
        report = {"schema": VALIDATION_SCHEMA_ID, "registry_valid": False, "validation_ceiling": VALIDATION_CEILING, "errors": [_typed_error_entry(exc)]}
        return 2, report
    try:
        result = status_for_consumer(payload, consumer_id, repo_root=_repo_root())
    except Exception as exc:
        report = {"schema": VALIDATION_SCHEMA_ID, "registry_valid": False, "validation_ceiling": VALIDATION_CEILING, "errors": [_typed_error_entry(exc)]}
        return 2, report
    report = result.as_report()
    report["schema"] = VALIDATION_SCHEMA_ID
    report["validation_ceiling"] = VALIDATION_CEILING
    if result.consumer_state == "UNKNOWN":
        return 4, report
    if result.consumer_state == "BLOCKED":
        return 3, report
    return (0, report) if result.registry_valid else (2, report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="raptor.sourceops.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--registry", required=True)
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--registry", required=True)
    status_parser.add_argument("--consumer", required=True)
    args = parser.parse_args(argv)

    if args.command == "validate":
        code, report = _validate(args.registry)
        _emit(report)
        return code
    if args.command == "status":
        code, report = _status(args.registry, args.consumer)
        _emit(report)
        return code
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
