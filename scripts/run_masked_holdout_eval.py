"""Terminal masked-holdout VUS-authorization runner (Arm C gate-fidelity, AC-G8).

This is the ONLY entry point allowed to run the real masked-rerun that would
authorize scoring the ~6,700 held-out VUS. It requires an approved
`bp4pp3-predictor-policy` artifact (`raptor.eval.predictor_policy`) -- when
that artifact is missing, malformed, or not `status == "approved"`, this
runner emits a `GateDecision(status="BLOCKED_POLICY", vus_authorized=False)`
and computes ZERO metrics (no `precision=`/`recall=` value is ever printed
in that state -- there is nothing legitimate to report).

Even with an APPROVED policy, this runner still emits `BLOCKED_POLICY`
today: the masked-resource pipeline (Arm A) and the canonical scoring
adapter (Arm B) are out of scope for Arm C (gate-fidelity) and are not
wired into this script. This runner must NEVER fabricate a `PASS` by
skipping the actual masked-rerun -- an approved policy authorizes running
the rerun, it does not substitute for one.

Usage:
  python scripts/run_masked_holdout_eval.py --predictor-policy PATH
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Bootstrap `src`-layout import (this repo's scripts are only ever run with
# `raptor` editable-installed / PYTHONPATH=src; this NEW script is made
# self-contained so it also works invoked bare, e.g. under test, without
# requiring the caller to set up PYTHONPATH first).
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from raptor.eval.model import GateDecision  # noqa: E402
from raptor.eval.predictor_policy import PredictorPolicyError, load_predictor_policy  # noqa: E402


def _blocked(reason: str) -> GateDecision:
    """Build the fail-closed `BLOCKED_POLICY` decision -- `decide_gate` never
    emits this status; only this terminal runner does."""
    return GateDecision(
        status="BLOCKED_POLICY",
        stratum="",
        reason=reason,
        vus_authorized=False,
        per_stratum={},
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Terminal masked-holdout VUS-authorization runner (Arm C gate-fidelity). "
            "Requires an approved bp4pp3-predictor-policy artifact; never emits PASS "
            "without one, and never bypasses BLOCKED_POLICY."
        )
    )
    parser.add_argument(
        "--predictor-policy",
        required=True,
        help="Path to the bp4pp3-predictor-policy JSON artifact (raptor.eval.predictor_policy).",
    )
    args = parser.parse_args(argv)

    try:
        policy = load_predictor_policy(args.predictor_policy)
    except PredictorPolicyError as exc:
        decision = _blocked(f"predictor-policy artifact missing or malformed: {exc}")
        print(decision)
        return 0

    if not policy.approved:
        decision = _blocked(
            f"predictor-policy artifact is not approved (status={policy.status!r}); "
            "cannot authorize the masked-holdout rerun"
        )
        print(decision)
        return 0

    decision = _blocked(
        "predictor-policy is approved, but the masked-holdout scoring pipeline "
        "(Arm A masked resources / Arm B canonical adapter) is not wired into this "
        "runner -- never fabricate a PASS by skipping the actual masked rerun"
    )
    print(decision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
