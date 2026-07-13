"""Track `strength-policy-2026-07` — CLI entry point for the deterministic,
label-free strength-policy materiality probe (see
`raptor.scorer.strength_materiality` for the full contract/docstring).

Usage::

    python scripts/run_strength_materiality_probe.py BIAS_TSV --output REPORT_JSON

Exits 0 on success. The report is fully deterministic: running the probe
twice against the same input TSV (and the same committed
ladder/policy/scorer/eval configs) produces byte-identical JSON. This
script never scores, classifies, or promotes any variant, and never reads
a label/benchmark/held-out file -- it is a characterization probe only.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from raptor.scorer.strength_materiality import (
    canonical_json,
    compute_materiality,
    load_materiality_inputs,
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Strength-policy materiality probe: characterize how often pinned "
        "BIAS-3.0.0 emits a (criterion, strength) pair outside the current scorer vocab, "
        "over a real BIAS output TSV. Aggregate/non-identifying only -- never persists "
        "per-variant chromosome/position/ref/alt rows."
    )
    parser.add_argument("bias_tsv", help="Path to a pinned BIAS-2015 output TSV (18-column contract).")
    parser.add_argument("--output", required=True, help="Path to write the canonical materiality report JSON.")
    parser.add_argument(
        "--ladder", default="configs/eval/bias_strength_ladder.yaml", help="Path to the bias-strength-ladder YAML."
    )
    parser.add_argument(
        "--policy", default="configs/acmg/strength_policy.yaml", help="Path to the acmg-strength-policy YAML."
    )
    parser.add_argument(
        "--scorer-config", default="configs/acmg/tsc.yaml", help="Path to the current scorer config YAML."
    )
    parser.add_argument(
        "--eval-config", default="configs/eval/tsc2.yaml", help="Path to the eval-harness config YAML."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    inputs = load_materiality_inputs(
        ladder_path=args.ladder,
        policy_path=args.policy,
        scorer_config_path=args.scorer_config,
        eval_config_path=args.eval_config,
    )
    report = compute_materiality(args.bias_tsv, inputs)
    rendered = canonical_json(report)
    Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
