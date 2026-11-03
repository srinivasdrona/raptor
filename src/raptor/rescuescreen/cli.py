"""Command-line status reporting for RescueScreen entry gates."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from raptor.rescuescreen.gates import (
    entry_gate_report_to_dict,
    evaluate_entry_gates,
    load_entry_gate_manifest,
)
from raptor.rescuescreen.model import RescueScreenError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Report deterministic RescueScreen entry-gate status")
    subparsers = parser.add_subparsers(dest="command", required=True)
    status = subparsers.add_parser("status", help="validate a manifest and report lane readiness")
    status.add_argument("--manifest", required=True)
    return parser


def _write_json(payload: dict) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        manifest = load_entry_gate_manifest(args.manifest)
        report = evaluate_entry_gates(manifest)
    except RescueScreenError as exc:
        _write_json(
            {
                "schema": "rescuescreen.entry_gate_error.v1",
                "error_type": type(exc).__name__,
                "message": str(exc),
            }
        )
        return 2

    payload = entry_gate_report_to_dict(report)
    _write_json(payload)
    return 0 if report.overall_status == "READY_FOR_S1_REVIEW" else 3


if __name__ == "__main__":
    raise SystemExit(main())
