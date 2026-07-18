#!/usr/bin/env python
"""Slot 3 — `scripts/build_pp3bp4_transportability_report.py` — Stage B
dev-only transportability report CLI (RAPTOR PP3/BP4 shadow policy, steps
2-7).

Derives the real dev/holdout composition via
`raptor.eval.pp3bp4_transportability.derive_dev_split_composition` (never
hardcoded), computes the pathogenic/benign power floor, and writes a
deterministic `BLOCKED_DATA` (`power_status: UNDERPOWERED`) artifact -- no
dev REVEL score table exists yet to evaluate, and the missense dev
pathogenic count (24) is below the 36-count power floor regardless.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from raptor.eval.config import load_config as load_eval_config  # noqa: E402
from raptor.eval.model import BenchmarkRow  # noqa: E402
from raptor.eval.pp3bp4_candidate_policy import load_candidate_policy  # noqa: E402
from raptor.eval.pp3bp4_transportability import (  # noqa: E402
    derive_dev_split_composition,
    get_power_status,
)

_DEFAULT_POLICY = "configs/eval/pp3bp4_candidate_policy.json"
_DEFAULT_SOURCE_REGISTER = "configs/eval/pp3bp4_source_register.yaml"
_POWER_FLOOR = 36


def _load_benchmark_rows(path: Path) -> list[BenchmarkRow]:
    rows: list[BenchmarkRow] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            rows.append(
                BenchmarkRow(
                    variant_id=data["variant_id"],
                    label=data["label"],
                    variant_class=data["variant_class"],
                    source=data.get("source"),
                    snapshot=data.get("snapshot"),
                )
            )
    return rows


def _canonical_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_transportability_payload(
    *,
    benchmark_path: Path,
    eval_config_path: Path,
    report_date: str,
    policy_path: str = _DEFAULT_POLICY,
    source_register_path: str = _DEFAULT_SOURCE_REGISTER,
) -> dict:
    """Build the deterministic `tsc-pp3bp4-transportability/1` payload
    (content_hash excluded, added by the caller)."""
    benchmark_rows = _load_benchmark_rows(benchmark_path)
    eval_config = load_eval_config(str(eval_config_path))
    composition = derive_dev_split_composition(benchmark_rows, eval_config)
    missense = composition["missense_composition"]
    power_status = get_power_status(
        missense["pathogenic"], missense["benign"], power_floor=_POWER_FLOOR
    )

    _, provenance = load_candidate_policy(policy_path, source_register_path)

    payload = {
        "schema": "tsc-pp3bp4-transportability/1",
        "status": "BLOCKED_DATA",
        "power_status": power_status,
        "report_date": report_date,
        "policy_source_sha256": provenance.policy_source_sha256,
        "source_register_sha256": provenance.source_register_sha256,
        "partition": {"n_dev": composition["n_dev"], "n_holdout": composition["n_holdout"]},
        "partition_derivation": (
            "derived via raptor.eval.split.split_benchmark against configs/eval/tsc2.yaml "
            "(seed 20260701, holdout_fraction 0.7); never a hardcoded count"
        ),
        "scope": ["TSC1 missense", "TSC2 missense"],
        "predeclared_metrics": ["precision", "recall", "concordance"],
        "missense_composition": missense,
        "power_note": (
            f"dev missense pathogenic count ({missense['pathogenic']}) is below the "
            f"{_POWER_FLOOR}-count power floor; transportability is predeclared UNDERPOWERED"
        ),
        "missing_artifact": (
            "dev REVEL score table (data/census/tsc_pp3bp4_dev_score_acquisition_2026-07.json) "
            "has not been produced; no structured REVEL score exists to evaluate"
        ),
        "required_build_steps": [
            "resolve every scripts/export_dev_vcf.py BLOCKED_DATA prerequisite",
            "produce and attest the dev REVEL score table (pp3bp4_score_table.load_and_validate_score_table)",
            "re-run scripts/build_pp3bp4_transportability_report.py against the attested score table",
        ],
        "prohibited": [
            "reading held-out scores or held-out criterion outputs",
            "reading VUS criterion outputs",
            "treating BLOCKED_DATA as transportability validation evidence",
            "tuning any PP3/BP4 threshold against this report",
        ],
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", default="D:/AIProjects/raptor-data/clinvar/benchmark/benchmark.jsonl", type=Path)
    parser.add_argument("--eval-config", default="configs/eval/tsc2.yaml", type=Path)
    parser.add_argument("--report-date", required=True, help="explicit report date/as-of (never wall clock)")
    parser.add_argument("--policy", default=_DEFAULT_POLICY)
    parser.add_argument("--source-register", default=_DEFAULT_SOURCE_REGISTER)
    parser.add_argument("--output", required=True, type=Path, help="artifact output path")
    args = parser.parse_args(argv)

    payload = build_transportability_payload(
        benchmark_path=args.benchmark,
        eval_config_path=args.eval_config,
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
