"""PRD-06 sec 10.3 `gate.py` — the VUS-authorization gate (FR6/AC5).

Gate-fidelity (Arm C, BREAKING migration): the single honesty boundary
between "we measured this" and "we may run on the ~6,700 VUS" now compares
the 95% Clopper-Pearson LOWER bound (`Metrics.precision_lb`/`recall_lb`/
`benign_precision_lb`/`benign_recall_lb`), never the point estimate, against
a per-stratum `EvalConfig.oracle_thresholds` map (`{confidence, strata:
{name: {precision, recall, gating, directions}}}`). The MISSENSE stratum
remains the binding gating stratum (R-A2c — never `overall`, which can
average away a bad TSC2-missense result); `truncating` is a second
hard-gated stratum where powered (its n=1 benign direction is report-only,
never gating). An EMPTY/missing-missense threshold block is the honest
pre-Oracle state (GP-9/H13) and MUST yield `UNVERIFIED`, never `PASS` —
checked before anything else, so no metric value, however good, can force a
pass while thresholds are unset. A below-`min_count_per_class` stratum
yields `UNDERPOWERED`, never `PASS`.
"""
from __future__ import annotations

import math
from typing import Dict, List

from .config import EvalConfig
from .model import GateDecision, Metrics, StratumVerdict

_GATING_STRATUM = "missense"

#: Direction -> the `Metrics` lower-bound field names that direction reads
#: (BLOCKER-1-equivalent: precision/recall govern BOTH directions the
#: stratum's `directions` list names, never only the pathogenic one).
_DIRECTION_LB_FIELDS: Dict[str, tuple] = {
    "pathogenic": ("precision_lb", "recall_lb"),
    "benign": ("benign_precision_lb", "benign_recall_lb"),
}

#: Direction -> the per-truth-class / per-class-CALLED count fields the
#: min-count coverage floor reads for that direction (FR5 defense-in-depth
#: -- a stratum can be "powered" for pathogenic while still underpowered for
#: benign, e.g. truncating-benign n=1; only the directions actually gated
#: for a stratum are required to clear the floor).
_DIRECTION_COUNT_FIELDS: Dict[str, tuple] = {
    "pathogenic": ("path_actual", "path_called"),
    "benign": ("benign_actual", "benign_called"),
}


def _valid_threshold(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0.0 < value <= 1.0


def _unmet_reasons(m: Metrics, spec: dict, directions: List[str]) -> List[str]:
    """Return every `(field=value<threshold)` reason a stratum's gated
    directions fail on the LOWER bound. A malformed/incomplete spec (no
    directions, or a non-finite/out-of-range precision/recall threshold) is
    always unmet -- never silently satisfied (defense-in-depth for a
    hand-built config bypassing `load_config`'s own schema check)."""
    precision_threshold = spec.get("precision")
    recall_threshold = spec.get("recall")
    if not directions or not _valid_threshold(precision_threshold) or not _valid_threshold(recall_threshold):
        return [f"malformed or empty stratum threshold spec: {spec!r}"]

    reasons: List[str] = []
    for direction in directions:
        precision_field, recall_field = _DIRECTION_LB_FIELDS[direction]
        precision_lb = getattr(m, precision_field, None)
        recall_lb = getattr(m, recall_field, None)
        if not (isinstance(precision_lb, (int, float)) and math.isfinite(precision_lb) and precision_lb >= precision_threshold):
            reasons.append(f"{precision_field}={precision_lb!r}<{precision_threshold!r}")
        if not (isinstance(recall_lb, (int, float)) and math.isfinite(recall_lb) and recall_lb >= recall_threshold):
            reasons.append(f"{recall_field}={recall_lb!r}<{recall_threshold!r}")
    return reasons


def _coverage_ok(m: Metrics, directions: List[str], min_count_per_class: int) -> bool:
    """Fail-closed per-direction coverage floor (FR5): only the directions a
    stratum actually gates must clear BOTH the per-truth-class AND
    per-class-CALLED count floors -- never trust a hand-built `gating=True`
    blindly (MINOR/round-6 defense-in-depth, now per-direction so a
    pathogenic-only hard gate, e.g. truncating, is not blocked by an
    unrelated report-only benign direction, e.g. truncating-benign n=1)."""
    if min_count_per_class <= 0:
        return False
    for direction in directions:
        actual_field, called_field = _DIRECTION_COUNT_FIELDS[direction]
        actual = m.counts.get(actual_field)
        called = m.counts.get(called_field)
        if actual is None or called is None or min(actual, called) < min_count_per_class:
            return False
    return True


def _evaluate_stratum(m, spec: dict, min_count_per_class: int) -> tuple:
    """Evaluate one stratum's spec against its `Metrics` (or `None` if the
    stratum has no computed metrics at all). Returns
    `(result, verdict, reasons)` where `result` is one of
    "underpowered" | "fail" | "pass" -- the coverage check runs LAST,
    mirroring the pre-existing FR6 authorization-boundary order: a stratum
    that fails the metric comparison is `FAIL` regardless of coverage,
    exactly like the pre-lower-bound gate."""
    directions = [d for d in spec.get("directions", []) if d in _DIRECTION_LB_FIELDS]

    if m is None:
        verdict = StratumVerdict(
            precision_lb=0.0, recall_lb=0.0, threshold=dict(spec), met=False,
            gating=bool(spec.get("gating", False)), powered=False,
        )
        return "underpowered", verdict, ["stratum absent from computed metrics"]

    unmet = _unmet_reasons(m, spec, directions)
    if unmet:
        verdict = StratumVerdict(
            precision_lb=getattr(m, "precision_lb", 0.0), recall_lb=getattr(m, "recall_lb", 0.0),
            threshold=dict(spec), met=False, gating=bool(spec.get("gating", False)), powered=True,
        )
        return "fail", verdict, unmet

    if not _coverage_ok(m, directions, min_count_per_class):
        verdict = StratumVerdict(
            precision_lb=getattr(m, "precision_lb", 0.0), recall_lb=getattr(m, "recall_lb", 0.0),
            threshold=dict(spec), met=False, gating=bool(spec.get("gating", False)), powered=False,
        )
        return "underpowered", verdict, [
            "cannot confirm per-truth-class + per-class CALLED coverage for the gated "
            "direction(s) (FR5)"
        ]

    verdict = StratumVerdict(
        precision_lb=getattr(m, "precision_lb", 0.0), recall_lb=getattr(m, "recall_lb", 0.0),
        threshold=dict(spec), met=True, gating=bool(spec.get("gating", False)), powered=True,
    )
    return "pass", verdict, []


def decide_gate(metrics: Dict[str, Metrics], config: EvalConfig) -> GateDecision:
    """Decide PASS/FAIL/UNVERIFIED/UNDERPOWERED from the missense-stratified
    (and, where powered, truncating-stratified) held-out 95% Clopper-Pearson
    LOWER bound (FR6/AC5, gate-fidelity Arm C). `vus_authorized` is `True`
    iff `status == "PASS"`. `decide_gate` never emits `BLOCKED_POLICY` --
    that status is reserved for the terminal masked-rerun harness
    (`scripts/run_masked_holdout_eval.py`)."""
    oracle_thresholds = config.oracle_thresholds or {}
    strata_cfg = oracle_thresholds.get("strata") or {}

    if not oracle_thresholds or not strata_cfg or _GATING_STRATUM not in strata_cfg:
        return GateDecision(
            status="UNVERIFIED",
            stratum=_GATING_STRATUM,
            reason=(
                "oracle_thresholds is empty or missing the missense gating stratum -- no "
                "pre-registered target (GP-9/H13); never invent one"
            ),
            vus_authorized=False,
            per_stratum={},
        )

    # BLOCKER-2 defense-in-depth: min_count_per_class<=0 disables every
    # per-direction coverage floor (FR5) -- a hand-built config bypassing
    # `load_config`'s own `>= 1` check must never be able to authorize.
    if config.min_count_per_class <= 0:
        return GateDecision(
            status="UNVERIFIED",
            stratum=_GATING_STRATUM,
            reason=(
                f"invalid config -- min_count_per_class={config.min_count_per_class!r} must be "
                ">= 1; cannot authorize"
            ),
            vus_authorized=False,
            per_stratum={},
        )

    per_stratum: Dict[str, StratumVerdict] = {}

    missense_spec = strata_cfg[_GATING_STRATUM]
    missense_metrics = metrics.get(_GATING_STRATUM)
    missense_result, missense_verdict, missense_reasons = _evaluate_stratum(
        missense_metrics, missense_spec, config.min_count_per_class
    )
    per_stratum[_GATING_STRATUM] = missense_verdict

    if missense_result == "underpowered":
        return GateDecision(
            status="UNDERPOWERED",
            stratum=_GATING_STRATUM,
            reason="; ".join(missense_reasons),
            vus_authorized=False,
            per_stratum=per_stratum,
        )
    if missense_result == "fail":
        return GateDecision(
            status="FAIL",
            stratum=_GATING_STRATUM,
            reason="missense metric(s) below Oracle threshold (95% CI lower bound): "
            + "; ".join(missense_reasons),
            vus_authorized=False,
            per_stratum=per_stratum,
        )

    # Missense clears -- check every OTHER hard-gated stratum (e.g.
    # truncating). Where powered and unmet -> FAIL; where not powered, it is
    # report-only for this decision (truncating-benign n=1 never gates).
    for name, spec in strata_cfg.items():
        if name == _GATING_STRATUM or not spec.get("gating"):
            continue
        result, verdict, reasons = _evaluate_stratum(metrics.get(name), spec, config.min_count_per_class)
        per_stratum[name] = verdict
        if result == "fail":
            return GateDecision(
                status="FAIL",
                stratum=name,
                reason=f"{name} metric(s) below Oracle threshold (95% CI lower bound): " + "; ".join(reasons),
                vus_authorized=False,
                per_stratum=per_stratum,
            )
        # "underpowered" for a secondary stratum does not block PASS -- it is
        # descriptive-only until that stratum itself is adequately powered
        # (slot 2 §1/§5: truncating hard-gates only "where powered").

    return GateDecision(
        status="PASS",
        stratum=_GATING_STRATUM,
        reason=(
            "missense stratum meets every Oracle pre-registered threshold on the 95% "
            "Clopper-Pearson lower bound; every other hard-gated stratum (where powered) "
            "also clears"
        ),
        vus_authorized=True,
        per_stratum=per_stratum,
    )
