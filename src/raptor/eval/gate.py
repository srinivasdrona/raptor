"""PRD-06 sec 10.3 `gate.py` — the VUS-authorization gate (FR6/AC5).

The single honesty boundary between "we measured this" and "we may run on
the 6,700 VUS": checks the MISSENSE-stratified held-out metric (R-A2c —
never `overall`, which can average away a bad TSC2-missense result) against
`config.oracle_thresholds`. An EMPTY threshold block is the honest
pre-Oracle state (GP-9/H13) and MUST yield `UNVERIFIED`, never `PASS` —
checked before anything else, so no metric value, however good, can force a
pass while thresholds are unset.
"""
from __future__ import annotations

import math
from typing import Dict

from .config import EvalConfig
from .model import GateDecision, Metrics

_GATING_STRATUM = "missense"

#: The only metric names a threshold key may name, read via an explicit
#: lookup (never `getattr`) so a bogus key or non-finite value can never be
#: silently "satisfied" into a PASS (BLOCKER 1). A `precision`/`recall`
#: threshold governs BOTH the pathogenic AND benign direction (BLOCKER-1
#: round-4): a model that discriminates one direction well but the other
#: poorly must not pass on that threshold. `concordance` governs only itself.
#: Each entry is `(value_name, value)` pairs so an UNMET reason can name
#: exactly which governed value fell short.
_METRIC_LOOKUP = {
    "precision": lambda m: (("precision", m.precision), ("benign_precision", m.benign_precision)),
    "recall": lambda m: (("recall", m.recall), ("benign_recall", m.benign_recall)),
    "concordance": lambda m: (("concordance", m.concordance),),
}

#: precision AND recall are mandatory gating targets (BLOCKER 1) -- a
#: concordance-only (or precision-only/recall-only) `oracle_thresholds`
#: block must never authorize a PASS, even if built by hand bypassing
#: `load_config`'s own schema check.
_REQUIRED_GATING_METRICS: frozenset[str] = frozenset({"precision", "recall"})


def decide_gate(metrics: Dict[str, Metrics], config: EvalConfig) -> GateDecision:
    """Decide PASS/FAIL/UNVERIFIED/UNDERPOWERED from the missense-stratified
    held-out metric (FR6/AC5). `vus_authorized` is `True` iff `status ==
    "PASS"`."""
    if not config.oracle_thresholds:
        return GateDecision(
            status="UNVERIFIED",
            stratum=_GATING_STRATUM,
            reason="oracle_thresholds is empty -- no pre-registered target (GP-9/H13); never invent one",
            vus_authorized=False,
        )

    # BLOCKER-2 defense-in-depth: min_count_per_class<=0 disables both the
    # per-truth-class and per-class CALLED coverage floors (FR5) -- a
    # hand-built config bypassing `load_config`'s own `>= 1` check must never
    # be able to authorize a VUS run.
    if config.min_count_per_class <= 0:
        return GateDecision(
            status="UNVERIFIED",
            stratum=_GATING_STRATUM,
            reason=(
                f"invalid config -- min_count_per_class={config.min_count_per_class!r} must be "
                ">= 1; cannot authorize"
            ),
            vus_authorized=False,
        )

    missing_required = _REQUIRED_GATING_METRICS - config.oracle_thresholds.keys()
    if missing_required:
        return GateDecision(
            status="UNVERIFIED",
            stratum=_GATING_STRATUM,
            reason=(
                "insufficient pre-registered targets -- precision+recall required "
                f"(missing: {sorted(missing_required)}); concordance can never substitute"
            ),
            vus_authorized=False,
        )

    m = metrics.get(_GATING_STRATUM)
    if m is None:
        return GateDecision(
            status="UNVERIFIED",
            stratum=_GATING_STRATUM,
            reason="missense stratum not present in computed metrics",
            vus_authorized=False,
        )

    if not m.gating:
        return GateDecision(
            status="UNDERPOWERED",
            stratum=_GATING_STRATUM,
            reason=(
                f"missense stratum below min_count_per_class={config.min_count_per_class} "
                "(FR5) -- descriptive only, never gating"
            ),
            vus_authorized=False,
        )

    unmet = []
    for metric_name, threshold in config.oracle_thresholds.items():
        getter = _METRIC_LOOKUP.get(metric_name)
        governed = getter(m) if getter is not None else None
        threshold_ok = (
            isinstance(threshold, (int, float))
            and math.isfinite(threshold)
            and (0.0 < threshold <= 1.0)
        )
        # A threshold naming a non-metric, or a non-finite/invalid threshold
        # itself: always UNMET, never satisfied.
        if governed is None or not threshold_ok:
            unmet.append((metric_name, governed, threshold))
            continue
        for value_name, value in governed:
            value_ok = isinstance(value, (int, float)) and math.isfinite(value)
            # Non-finite/missing governed value, or below threshold: UNMET.
            if not value_ok or not (value >= threshold):
                unmet.append((value_name, value, threshold))

    if unmet:
        reason = "missense metric(s) below Oracle threshold: " + ", ".join(
            f"{name}={value!r}<{threshold!r}" for name, value, threshold in unmet
        )
        return GateDecision(status="FAIL", stratum=_GATING_STRATUM, reason=reason, vus_authorized=False)

    # MINOR: the coverage guarantee must be enforced fail-CLOSED at the
    # authorization point itself -- a Metrics that meets every threshold but
    # lacks per-class CALLED coverage counts (e.g. hand-built with `counts={}`)
    # must NOT be authorized: we cannot confirm the model was actually
    # measured on both truth classes.
    path_called = m.counts.get("path_called")
    benign_called = m.counts.get("benign_called")
    path_actual = m.counts.get("path_actual")
    benign_actual = m.counts.get("benign_actual")
    required_counts = (path_called, benign_called, path_actual, benign_actual)
    if any(c is None for c in required_counts) or min(required_counts) < config.min_count_per_class:
        return GateDecision(
            status="UNDERPOWERED",
            stratum=_GATING_STRATUM,
            reason=(
                "cannot confirm per-truth-class + per-class CALLED coverage -- missing/"
                "insufficient path_called/benign_called/path_actual/benign_actual counts "
                "(FR5); descriptive only, never gating"
            ),
            vus_authorized=False,
        )

    return GateDecision(
        status="PASS",
        stratum=_GATING_STRATUM,
        reason="missense stratum meets every Oracle pre-registered threshold",
        vus_authorized=True,
    )
