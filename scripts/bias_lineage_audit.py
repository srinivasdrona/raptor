"""Slot 2 sec 1.4.4 `bias_lineage_audit.py` — standalone BIAS lineage audit CLI.

Usage::

    python scripts/bias_lineage_audit.py BIAS_TSV --output REPORT_JSON \\
        [--policy configs/eval/bias_lineage.yaml]

Loads the lineage policy + the full pinned-BIAS output TSV (via
`BiasTsvSource`, the committed 18-column contract -- never a label file),
runs `audit_lineage`, ALWAYS persists the canonical report JSON to
`REPORT_JSON` and prints the SAME canonical JSON to stdout (in both the
clean and blocked case), then calls `enforce_lineage`: exits `0` iff the
report is clean, non-zero iff `report.blocked`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from raptor.eval.config import load_config as load_eval_config
from raptor.eval.lineage_audit import LineageGateError, audit_lineage, enforce_lineage
from raptor.eval.lineage_policy import load_lineage_policy
from raptor.scorer.bias_source import BiasTsvSource
from raptor.scorer.config import load_config as load_scorer_config

#: Default policy pin (slot 2 sec 1.1) -- the single machine-readable
#: source of truth for BIAS criterion lineage.
_DEFAULT_POLICY_PATH = "configs/eval/bias_lineage.yaml"
#: The two existing production registries this audit reconciles against
#: (slot 2 sec 1.6) -- not exposed as CLI flags; the CLI's only inputs are
#: the BIAS TSV, the output path, and (optionally) the policy path.
_SCORER_CONFIG_PATH = "configs/acmg/tsc.yaml"
_EVAL_CONFIG_PATH = "configs/eval/tsc2.yaml"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit a BIAS-2015 output TSV against the BIAS criterion lineage policy "
        "and fail-closed gate on any ClinVar-lineage-suspect scored criterion."
    )
    parser.add_argument("bias_tsv", help="Path to a pinned BIAS-2015 output TSV (18-column contract).")
    parser.add_argument("--output", required=True, help="Path to write the canonical lineage audit report JSON.")
    parser.add_argument(
        "--policy",
        default=_DEFAULT_POLICY_PATH,
        help=f"Path to the lineage policy YAML (default: {_DEFAULT_POLICY_PATH}).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    policy = load_lineage_policy(args.policy)
    scorer_config = load_scorer_config(_SCORER_CONFIG_PATH)
    eval_config = load_eval_config(_EVAL_CONFIG_PATH)

    source = BiasTsvSource(args.bias_tsv)
    report = audit_lineage(source.records(), policy=policy, scorer_config=scorer_config, eval_config=eval_config)

    canonical_json = json.dumps(report.to_dict(), sort_keys=True, indent=2)
    Path(args.output).write_text(canonical_json, encoding="utf-8")
    print(canonical_json)

    try:
        enforce_lineage(report)
    except LineageGateError:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
