"""Slot 3 — `pp3bp4_transportability.py` — Stage B dev-only transportability
evaluation (RAPTOR PP3/BP4 shadow policy, steps 2-7).

Stage B (Slot 2 Rule 4): may read frozen dev labels only AFTER Stage A's
`ScoreTableAttestation` has been verified, rejects any extra/held-out id,
and never writes a label back into the score table or policy. Dev
composition is always DERIVED from the repository's real
`raptor.eval.split.split_benchmark` -- never hardcoded.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .config import EvalConfig
from .model import BenchmarkRow
from .pp3bp4_score_table import ScoreTableAttestation
from .split import split_benchmark


class TransportabilityError(ValueError):
    """Raised on a missing/mismatched `ScoreTableAttestation`, a
    `dev_id_set_sha256` mismatch, or any held-out/extra id found in the
    submitted rows. Fail-closed throughout."""


@dataclass
class TransportabilityReport:
    """A Stage-B, label-blind transportability computation kernel result.

    Deliberately narrow: this is the disjointness-proven, dev-scoped score
    coverage a real transportability metrics computation would consume --
    it never reads or carries a benchmark label itself (Rule 4/T-E1)."""

    n_dev: int
    n_rows: int
    n_scored: int
    coverage: float
    dev_id_set_sha256: str
    table_content_sha256: str
    predictor: str
    predictor_version: str


def _compute_dev_id_set_hash(dev_ids: list[str]) -> str:
    digest = hashlib.sha256()
    for variant_id in sorted(dev_ids):
        digest.update(variant_id.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def derive_dev_split_composition(benchmark_rows: list[BenchmarkRow], eval_config: EvalConfig) -> dict:
    """Derive dev/holdout composition from the REAL benchmark + eval config
    (T-E2) -- always via `raptor.eval.split.split_benchmark`, never a
    hardcoded zero-arg count."""
    train_dev, holdout = split_benchmark(benchmark_rows, eval_config)
    missense = [r for r in train_dev if r.variant_class == "missense"]
    p_count = sum(1 for r in missense if r.label == "P")
    lp_count = sum(1 for r in missense if r.label == "LP")
    b_count = sum(1 for r in missense if r.label == "B")
    lb_count = sum(1 for r in missense if r.label == "LB")
    return {
        "n_dev": len(train_dev),
        "n_holdout": len(holdout),
        "missense_composition": {
            "pathogenic": p_count + lp_count,
            "benign": b_count + lb_count,
            "P": p_count,
            "LP": lp_count,
            "B": b_count,
            "LB": lb_count,
        },
    }


def get_power_status(pathogenic_count: int, benign_count: int, *, power_floor: int) -> str:
    """FR5-style power floor check (T-E2): UNDERPOWERED when either
    directional dev count falls below `power_floor`."""
    if pathogenic_count < power_floor or benign_count < power_floor:
        return "UNDERPOWERED"
    return "POWERED"


def evaluate_transportability(
    rows: list[dict],
    attestation: ScoreTableAttestation | None,
    *,
    benchmark_rows: list[BenchmarkRow],
    eval_config: EvalConfig,
    policy: Any,
) -> TransportabilityReport:
    """Stage-B transportability boundary (T-E1).

    Rejects a missing/mismatched attestation and any held-out/extra id
    before touching a single row. Labels are never read here and never
    written back -- this returns only dev-scoped coverage counts, never a
    label value or key."""
    if attestation is None:
        raise TransportabilityError(
            "transportability evaluation requires a ScoreTableAttestation; attestation is missing"
        )

    train_dev, holdout = split_benchmark(benchmark_rows, eval_config)
    dev_ids = [r.variant_id for r in train_dev]
    holdout_ids = {r.variant_id for r in holdout}
    dev_id_set = set(dev_ids)

    expected_dev_hash = _compute_dev_id_set_hash(dev_ids)
    if attestation.dev_id_set_sha256 != expected_dev_hash:
        raise TransportabilityError(
            "attestation dev_id_set_sha256 mismatch against the real dev split: "
            f"attestation={attestation.dev_id_set_sha256!r} actual={expected_dev_hash!r}"
        )

    for row in rows:
        variant_id = row["variant_id"]
        if variant_id in holdout_ids or variant_id not in dev_id_set:
            raise TransportabilityError(
                f"transportability row variant_id {variant_id!r} is not disjoint from the "
                "dev set (held-out or extra id rejected before any scoring)"
            )

    n_scored = sum(1 for row in rows if row.get("score") is not None)
    n_rows = len(rows)
    coverage = (n_scored / len(dev_ids)) if dev_ids else 1.0

    return TransportabilityReport(
        n_dev=len(dev_ids),
        n_rows=n_rows,
        n_scored=n_scored,
        coverage=coverage,
        dev_id_set_sha256=expected_dev_hash,
        table_content_sha256=attestation.table_content_sha256,
        predictor=policy.predictor,
        predictor_version=policy.predictor_version,
    )
