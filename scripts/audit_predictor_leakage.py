#!/usr/bin/env python
"""Slot 3 — `scripts/audit_predictor_leakage.py` — direct/component
training-manifest leakage audit CLI (RAPTOR PP3/BP4 shadow policy, steps
2-7).

Wraps `raptor.eval.predictor_leakage_audit.evaluate_leakage_audit` against
the REAL frozen benchmark and the `configs/eval/predictor_training_manifests.yaml`
registry, and writes a deterministic status artifact. No component/direct
training manifest is currently obtained -- the current status is `UNKNOWN`,
never `PASS` (Rule 5).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from raptor.eval.pp3bp4_candidate_policy import load_candidate_policy  # noqa: E402
from raptor.eval.predictor_leakage_audit import evaluate_leakage_audit  # noqa: E402

_DEFAULT_POLICY = "configs/eval/pp3bp4_candidate_policy.json"
_DEFAULT_SOURCE_REGISTER = "configs/eval/pp3bp4_source_register.yaml"
_DEFAULT_REGISTRY = "configs/eval/predictor_training_manifests.yaml"
_SPDI_RE = re.compile(r"^[A-Za-z]{1,4}_\d+\.\d+:\d+:[ACGTNacgtn]*:[ACGTNacgtn]*$")


def _canonical_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _normalization_failures(benchmark_path: Path) -> list[str]:
    failures: list[str] = []
    with benchmark_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            variant_id = json.loads(line)["variant_id"]
            if not _SPDI_RE.match(variant_id):
                failures.append(variant_id)
    return failures


def build_leakage_audit_payload(
    *,
    benchmark_path: Path,
    registry_path: str,
    report_date: str,
    policy_path: str = _DEFAULT_POLICY,
    source_register_path: str = _DEFAULT_SOURCE_REGISTER,
) -> dict:
    """Build the deterministic `tsc-predictor-leakage-audit/1` payload
    (content_hash excluded, added by the caller)."""
    result = evaluate_leakage_audit(
        benchmark_path=str(benchmark_path),
        direct_manifest_path=None,
        component_manifest_paths=None,
        registry_path=registry_path,
    )
    _, provenance = load_candidate_policy(policy_path, source_register_path)

    payload = {
        "schema": "tsc-predictor-leakage-audit/1",
        "status": result.status.value,
        "report_date": report_date,
        "policy_source_sha256": provenance.policy_source_sha256,
        "source_register_sha256": provenance.source_register_sha256,
        "benchmark_id_set_sha256": result.benchmark_id_set_sha256,
        "benchmark_n": result.benchmark_n,
        "scope": ["TSC1 missense", "TSC2 missense"],
        "direct_overlap": result.direct_overlap,
        "component_overlap": result.component_overlap,
        "normalization_failures": _normalization_failures(benchmark_path),
        "decision": (
            "no PP3/BP4 activation; leakage status is UNKNOWN because no REVEL/BayesDel-noAF/"
            "MutPred2/VEST4/BIAS-composite training manifest is currently obtained and hash-verified"
        ),
        "interpretation_limits": (
            "UNKNOWN never implies PASS; this audit proves no overlap ONLY once every direct and "
            "component training manifest named in the registry is available, hash-verified, and "
            "normalized. It reads only benchmark variant_id values -- never labels, held-out "
            "criterion outputs, or VUS criterion outputs."
        ),
        "inputs": {
            "benchmark_path": str(benchmark_path),
            "registry_path": str(registry_path),
        },
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", default="D:/AIProjects/raptor-data/clinvar/benchmark/benchmark.jsonl", type=Path)
    parser.add_argument("--registry", default=_DEFAULT_REGISTRY)
    parser.add_argument("--report-date", required=True, help="explicit report date/as-of (never wall clock)")
    parser.add_argument("--policy", default=_DEFAULT_POLICY)
    parser.add_argument("--source-register", default=_DEFAULT_SOURCE_REGISTER)
    parser.add_argument("--output", required=True, type=Path, help="artifact output path")
    args = parser.parse_args(argv)

    payload = build_leakage_audit_payload(
        benchmark_path=args.benchmark,
        registry_path=args.registry,
        report_date=args.report_date,
        policy_path=args.policy,
        source_register_path=args.source_register,
    )
    content_hash = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    payload["content_hash"] = content_hash

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(_canonical_bytes(payload))

    print(json.dumps({"status": payload["status"], "content_hash": content_hash}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
