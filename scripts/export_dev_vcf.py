#!/usr/bin/env python
"""Slot 3 — `scripts/export_dev_vcf.py` — Stage A dev-partition export CLI
for the shadow REVEL PP3/BP4 policy (RAPTOR PP3/BP4 shadow policy, steps
2-7).

Reads the REAL frozen benchmark + eval config, derives the dev/holdout
split via `raptor.eval.split.split_benchmark` (never hardcoded), and
writes a deterministic `BLOCKED_DATA` status artifact naming every current
missing prerequisite (reference genome access, structured REVEL/dbNSFP
annotation runtime, predictor/data version pin, license record). This
script never reads or writes a label -- only `variant_id`s derived from the
dev/holdout split.
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
from raptor.eval.split import split_benchmark  # noqa: E402

_DEFAULT_POLICY = "configs/eval/pp3bp4_candidate_policy.json"
_DEFAULT_SOURCE_REGISTER = "configs/eval/pp3bp4_source_register.yaml"

#: The current, always-true dev score-acquisition blockers (Slot 3
#: `missing_prerequisites`) -- honest today regardless of `--reference-root`:
#: RAPTOR has no structured REVEL/dbNSFP annotation runtime, no pinned
#: predictor/data version, and no verified license record.
_ALWAYS_MISSING_PREREQUISITES: tuple[str, ...] = (
    "structured REVEL/dbNSFP annotation runtime (Nirvana or equivalent) is not provisioned",
    "REVEL predictor_version/data_version pin is not confirmed (remains confirm-pending)",
    "REVEL license/permitted-use record is not verified (license_status remains confirm_pending)",
)


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


def _id_set_hash(ids: list[str]) -> str:
    digest = hashlib.sha256()
    for variant_id in sorted(ids):
        digest.update(variant_id.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _canonical_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_status_payload(
    *,
    benchmark_path: Path,
    eval_config_path: Path,
    reference_root: str,
    report_date: str,
    policy_path: str = _DEFAULT_POLICY,
    source_register_path: str = _DEFAULT_SOURCE_REGISTER,
) -> dict:
    """Build the deterministic `tsc-pp3bp4-dev-score-acquisition/1` payload
    (content_hash excluded, added by the caller)."""
    benchmark_rows = _load_benchmark_rows(benchmark_path)
    eval_config = load_eval_config(str(eval_config_path))
    train_dev, holdout = split_benchmark(benchmark_rows, eval_config)

    benchmark_ids = [row.variant_id for row in benchmark_rows]
    dev_ids = [row.variant_id for row in train_dev]

    _, provenance = load_candidate_policy(policy_path, source_register_path)

    missing_prerequisites = list(_ALWAYS_MISSING_PREREQUISITES)
    if not Path(reference_root).is_dir():
        missing_prerequisites.insert(
            0,
            f"reference genome FASTA root does not resolve to an existing directory: {reference_root!r}",
        )

    payload = {
        "schema": "tsc-pp3bp4-dev-score-acquisition/1",
        "status": "BLOCKED_DATA",
        "report_date": report_date,
        "policy_source_sha256": provenance.policy_source_sha256,
        "source_register_sha256": provenance.source_register_sha256,
        "benchmark_id_set_sha256": _id_set_hash(benchmark_ids),
        "dev_id_set_sha256": _id_set_hash(dev_ids),
        "n_dev": len(train_dev),
        "n_holdout": len(holdout),
        "reference_pins": ["NC_000009.12", "NC_000016.10"],
        "missing_prerequisites": missing_prerequisites,
        "required_build_steps": [
            "pin REVEL predictor_version/data_version in configs/eval/pp3bp4_candidate_policy.json",
            "obtain and verify the REVEL license/permitted-use record",
            "provision structured REVEL/dbNSFP annotation runtime",
            "resolve --reference-root to a verified GRCh38 FASTA store",
            "regenerate the dev score table via scripts/export_dev_vcf.py",
        ],
        "output_policy": (
            "no dev REVEL scores are exported while any prerequisite above is unmet; this "
            "script writes only this deterministic BLOCKED_DATA status artifact"
        ),
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", required=True, type=Path, help="frozen benchmark JSONL")
    parser.add_argument("--eval-config", required=True, type=Path, help="raptor.eval EvalConfig YAML")
    parser.add_argument("--reference-root", required=True, help="reference FASTA root")
    parser.add_argument("--benchmark-snapshot", required=True, help="benchmark snapshot id (provenance only)")
    parser.add_argument("--out-dir", required=True, type=Path, help="dev export output directory")
    parser.add_argument("--status-output", required=True, type=Path, help="status artifact output path")
    parser.add_argument("--report-date", required=True, help="explicit report date/as-of (never wall clock)")
    parser.add_argument("--policy", default=_DEFAULT_POLICY)
    parser.add_argument("--source-register", default=_DEFAULT_SOURCE_REGISTER)
    args = parser.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)

    payload = build_status_payload(
        benchmark_path=args.benchmark,
        eval_config_path=args.eval_config,
        reference_root=args.reference_root,
        report_date=args.report_date,
        policy_path=args.policy,
        source_register_path=args.source_register,
    )
    content_hash = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    payload["content_hash"] = content_hash

    args.status_output.parent.mkdir(parents=True, exist_ok=True)
    args.status_output.write_bytes(_canonical_bytes(payload))

    print(json.dumps({"status": payload["status"], "content_hash": content_hash}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
